import anthropic
from pathlib import Path
import subprocess
from memory_management import store_memory, retrieve_memory, validate_memory_key
import json
import re
import requests
import os
import msal
import atexit

NAMESPACE = "meeting-digester"
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
CACHE_FILE = "token_cache.bin"

def load_cache():
    """Loads the MSAL token cache from a local file to avoid repeated logins."""
    cache = msal.SerializableTokenCache()
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                cache.deserialize(f.read())
        except Exception as e:
            print(f"[DEBUG] Cache load failed: {e}")
    return cache

def save_cache(cache):
    """Saves the MSAL token cache to a local file if it has changed."""
    if cache.has_state_changed:
        try:
            with open(CACHE_FILE, "w") as f:
                f.write(cache.serialize())
        except Exception as e:
            print(f"[DEBUG] Cache save failed: {e}")

def load_agent(agent_filename: str) -> str:
    agent_path = Path(f"src/agents_layer/{agent_filename}")
    if not agent_path.exists():
        raise FileNotFoundError(
            f"File not found: {agent_path}"
        )
    return agent_path.read_text(encoding="utf-8")

def initialise_swarm():
    try:
        result = subprocess.run(
            [
                "ruflo",
                "swarm", "init",
                "--topology", "hierarchical",
                "--max-agents", "5",
                "--strategy", "specialized"
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            print("An error occured in initialise_swarm")
            print(f"      {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        print("[WARNING] Swarm init timed out. Continuing anyway.")
    except FileNotFoundError:
        print("[WARNING] Ruflo CLI not found. Continuing without swarm init.")

def extract_json(raw: str):
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    text = text.strip()

    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in response:\n{raw}")

    json_str = match.group(1)

    # Normalize line endings and remove control characters that break json.loads
    json_str = json_str.replace("\r\n", "\n").replace("\r", "\n")
    json_str = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", json_str)

    return json.loads(json_str)

def get_graph_token() -> str:
    """
    Acquires a token using Device Code Flow with Persistent Caching.
    If 'token_cache.bin' is valid, the script skips the login prompt entirely.
    """
    client_id = os.environ.get("AZURE_CLIENT_ID", "").strip()
    # 'common' allows the user to log in with any Microsoft account and self-consent
    tenant_id = os.environ.get("AZURE_TENANT_ID", "common").strip()

    if not client_id:
        raise EnvironmentError("AZURE_CLIENT_ID missing from environment.")

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    scopes = ["Mail.ReadWrite", "User.Read"]

    # Initialize persistent cache and register auto-save
    cache = load_cache()
    atexit.register(save_cache, cache)

    app = msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)

    # Try silent login from cache first
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(scopes, account=accounts[0])
        if result:
            print("✅ Using cached Outlook token (Login skipped).")
            return result['access_token']

    # Otherwise, perform full Device Code login
    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        raise Exception(f"MSAL Error: {flow.get('error_description', 'Device flow failed')}")

    print("\n" + "="*60)
    print("📋 OUTLOOK LOGIN REQUIRED (First-time setup)")
    print(flow["message"])
    print("="*60 + "\n")

    result = app.acquire_token_by_device_flow(flow)
    
    if "access_token" in result:
        print("✅ Authentication successful and saved to cache!")
        return result['access_token']
    else:
        raise Exception(f"Could not acquire token: {result.get('error_description')}")

def create_outlook_draft(token: str, to: str, subject: str, body: str) -> dict:
    """Creates a single draft email in Outlook via the /me endpoint."""
    url = f"{GRAPH_API_BASE}/me/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    # Format body with HTML line breaks for better rendering
    html_body = body.replace("\n", "<br>")
    html_body = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", html_body)

    payload = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html_body},
        "toRecipients": [{"emailAddress": {"address": to}}],
    }

    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

# kinda a wrapper for calling agents with passed in markdown file as input
def run_planner_agent(client: anthropic.Anthropic):
    instructions = load_agent("planner_agent.md")
    transcript = retrieve_memory("meeting:transcript", NAMESPACE)
    roster = retrieve_memory("meeting:employees", NAMESPACE)

    user_message = f"""
        TRANSCRIPT:
        {transcript}

        EMPLOYEE ROSTER:
        {roster}

        Read both and return your routing decisions for the email agent as raw JSON.
    """

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=instructions,
        messages=[{"role": "user", "content": user_message}]
    )

    plan = extract_json(response.content[0].text)
    print("Planner Agent plan:\n", plan)
    store_memory("workflow:plan", plan, NAMESPACE)


def run_transcript_agent(client: anthropic.Anthropic):
    # load files
    instructions = load_agent("transcript_agent.md")

    transcript = retrieve_memory("meeting:transcript", NAMESPACE)

    # create user message
    user_message = f"""
        TRANSCRIPT:
        {transcript}

        Extract tasks and produce the summary. Return only the JSON object.
    """

    # get response
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=instructions,
        messages=[{"role": "user", "content": user_message}]
    )

    # set memory in mcp
    # response = response.content[0].text.strip()
    # parsed_response = json.loads(response)
    parsed_response = extract_json(response.content[0].text)
 
    # may need to validate these are not empty and strings
    summary = parsed_response.get("summary", "")
    tasks = parsed_response.get("tasks",   [])
    print("Transcript Agent summary: \n", summary)
    print("Transcript Agent tasks: \n", tasks)

    store_memory("transcript:summary", summary, NAMESPACE)
    store_memory("transcript:tasks", tasks, NAMESPACE)

def run_task_agent(client: anthropic.Anthropic):
    # 1. Load agent instructions from Task_agent.md
    agent_instructions = load_agent("task_agent.md")
 
    # 2. Pull required inputs from shared memory
    transcript_tasks = retrieve_memory("transcript:tasks", NAMESPACE)
    employee_information = retrieve_memory("meeting:employees", NAMESPACE)
 
    # 3. Validate inputs before proceeding
    if not transcript_tasks or not employee_information:
        raise ValueError("Task Agent: Missing required memory keys — aborting.")
 
    # 4. Build the prompt for the agent
    # same for email agent, is there a reason the instructions are put here?
    prompt = f"""
    Here are the tasks extracted from the transcript:
    {transcript_tasks}
 
    Here is the employee information:
    {employee_information}
 
    Assign each task to the appropriate employee with a deadline.
    Return only valid JSON matching the output format in your instructions.
    """
 
    # 5. Call the Claude API
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=agent_instructions,
        messages=[{"role": "user", "content": prompt}]
    )
 
    # 6. Extract and store the result
    parsed_task_assignments = extract_json(response.content[0].text)
    print("Task Agent format response:\n", parsed_task_assignments)
    store_memory("task:assignments", parsed_task_assignments, NAMESPACE)
 


# this is going to need to be updated to check if the planner agent determined a follow up email needs to be sent
def run_email_agent(client: anthropic.Anthropic):
    instructions = load_agent("email_agent.md")

    task_assignments = retrieve_memory("task:assignments", NAMESPACE)
    transcript_summary = retrieve_memory("transcript:summary", NAMESPACE)
    workflow_plan = retrieve_memory("workflow:plan", NAMESPACE)

    if not transcript_summary or not workflow_plan:
        raise ValueError("Email Agent: Missing required memory keys — aborting.")

    prompt = f"""
        Here is the workflow plan with routing decisions:
        {workflow_plan}

        Here is the meeting summary:
        {transcript_summary}

        Here are the task assignments (may be empty if send_task_emails is false):
        {task_assignments or "[]"}

        Draft the appropriate emails based on the routing decisions in the workflow plan.
        Return only raw JSON matching your output format.
    """

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system=instructions,
        messages=[{"role": "user", "content": prompt}]
    )

    parsed_draft_emails = extract_json(response.content[0].text)
    print("Email Agent format response:\n", parsed_draft_emails)
    store_memory("email:drafts", parsed_draft_emails, NAMESPACE)

def run_tool_agent(client: anthropic.Anthropic):
    """Orchestrates the actual creation of drafts using Microsoft Graph tools."""
    print("### Tool Agent: Executing Outlook Drafts ###")
    instructions = load_agent("tool_agent.md")
    email_drafts_raw = retrieve_memory("email:drafts", NAMESPACE)
    email_drafts = json.loads(email_drafts_raw) if isinstance(email_drafts_raw, str) else email_drafts_raw

    # Authentication step (automatically checks cache)
    token = get_graph_token()
    
    tools = [{
        "name": "create_outlook_draft",
        "description": "Creates a draft email in Outlook. Call once per email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "type": {"type": "string"}
            },
            "required": ["to", "subject", "body", "type"]
        }
    }]

    # Force Claude to skip conversation and go straight to tools
    messages = [{
        "role": "user", 
        "content": f"EXECUTE NOW. Create drafts for every email provided: {json.dumps(email_drafts)}"
    }]

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system=instructions + "\nSYSTEM OVERRIDE: Do not provide a text summary first. Immediately use tools.",
        tools=tools,
        messages=messages
    )

    results = []

    # Loop until the agent has completed all actions (end_turn)
    while response.stop_reason != "end_turn":
        if response.stop_reason == "tool_use":
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in tool_use_blocks:
                try:
                    draft = create_outlook_draft(token, block.input["to"], block.input["subject"], block.input["body"])
                    res = {"to": block.input["to"], "status": "success", "id": draft.get("id")}
                    print(f"Drafted for: {block.input['to']}")
                except Exception as e:
                    res = {"to": block.input["to"], "status": "failed", "error": str(e)}
                    print(f"Failed: {block.input['to']} — {e}")

                results.append(res)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(res)})

            messages.append({"role": "user", "content": tool_results})
            response = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=2048,
                system=instructions, tools=tools, messages=messages
            )
        else:
            # If Claude sends text, push it to proceed with tools
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": "Confirmed. Please proceed with all tool calls now."})
            response = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=2048,
                system=instructions, tools=tools, messages=messages
            )

    report = {"results": results, "summary": "Tool execution phase finished."}
    store_memory("tool:results", report, NAMESPACE)
    print("### Tool Agent: Execution Complete ###")

def start_workflow(
    client: anthropic.Anthropic,
):
    print("### Initializing swarm ###")
    initialise_swarm()
    print("### Successfully initialized swarm ###")

    # will need this when ready
    # run_tools_agent()
 
    # will edit these 2 for testing to add the files to the mcp if needed on error
    print("### Validating transcript and employee information ###")
    if not validate_memory_key("meeting:transcript", NAMESPACE):
        raise ValueError("meeting:transcript not found in memory")
    if not validate_memory_key("meeting:employees", NAMESPACE):
        raise ValueError("meeting:employees not found in memory")
    print("### Successfully validated transcript and employee information ###\n\n")
    
    print("### Running Planner agent ###")
    run_planner_agent(client)
    if not validate_memory_key("workflow:plan", NAMESPACE):
        raise ValueError("workflow:plan not found in memory")
    print("### Completed Planner agent ###\n\n")
    
    print("### Running Transcript agent ###")
    run_transcript_agent(client)
    if not validate_memory_key("transcript:summary", NAMESPACE):
        raise ValueError("transcript:summary not found in memory")
    if not validate_memory_key("transcript:tasks", NAMESPACE):
        raise ValueError("transcript:tasks not found in memory")
    print("### Completed Transcript agent ###\n\n")

    print("### Running Task agent ###")
    run_task_agent(client)
    if not validate_memory_key("task:assignments", NAMESPACE):
        raise ValueError("task:assignments not found in memory")
    print("### Completed Task agent ###\n\n")

    print("### Running email agent ###")
    run_email_agent(client)
    if not validate_memory_key("email:drafts", NAMESPACE):
        raise ValueError("email:drafts not found in memory")
    print("### Completed Email agent ###\n\n")
    
    print("### Running Tool agent ###")
    run_tool_agent(client)
    if not validate_memory_key("tool:results", NAMESPACE):
        raise ValueError("tool:results not found in memory")
    print("### Completed Tool agent ###\n\n")

    summary     = retrieve_memory("transcript:summary", NAMESPACE)
    tasks       = retrieve_memory("transcript:tasks",   NAMESPACE)
    assignments = retrieve_memory("task:assignments",   NAMESPACE)
    emails      = retrieve_memory("email:drafts",       NAMESPACE)
    tool_results = retrieve_memory("tool:results",      NAMESPACE)
    print("tool_results: ", tool_results)
    return summary, tasks, assignments, emails

def run_transcript_only(
    client: anthropic.Anthropic,
):
    initialise_swarm()
    if not validate_memory_key("meeting:transcript", NAMESPACE):
        raise ValueError("meeting:transcript not found in memory")
    if not validate_memory_key("meeting:employees", NAMESPACE):
        raise ValueError("meeting:employees not found in memory")
    
    run_transcript_agent(client)
    if not validate_memory_key("transcript:summary", NAMESPACE):
        raise ValueError("transcript:summary not found in memory")
    if not validate_memory_key("transcript:tasks", NAMESPACE):
        raise ValueError("transcript:tasks not found in memory")
    
    tasks = retrieve_memory("transcript:tasks",   NAMESPACE)
    return tasks
    
