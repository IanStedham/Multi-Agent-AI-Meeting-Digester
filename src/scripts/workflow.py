import anthropic
from pathlib import Path
import subprocess
from memory_management import store_memory, retrieve_memory, validate_memory_key
import json
import re
import requests
import os

NAMESPACE = "meeting-digester"
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

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
    Acquires a token using Device Code Flow. 
    Suitable for Personal accounts where Client Credentials flow is not allowed.
    """
    client_id = os.environ.get("AZURE_CLIENT_ID")
    # For personal accounts, tenant can be 'consumers' or 'common'
    tenant_id = os.environ.get("AZURE_TENANT_ID", "consumers") 

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    scopes = ["Mail.ReadWrite", "User.Read"]

    app = msal.PublicClientApplication(client_id, authority=authority)

    # First, try to get a token from the local cache
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(scopes, account=accounts[0])
        if result:
            return result['access_token']

    # If no cache, start the Device Code Flow
    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        raise Exception("Could not initiate device flow")

    # This will print a message in your terminal telling you where to go and what code to enter
    print("\n" + "!"*50)
    print(flow["message"])
    print("!"*50 + "\n")

    result = app.acquire_token_by_device_flow(flow)
    
    if "access_token" in result:
        return result['access_token']
    else:
        raise Exception(f"Could not acquire token: {result.get('error_description')}")

def create_outlook_draft(token: str, to: str, subject: str, body: str) -> dict:
    """
    Creates a draft. Note: removed user_email parameter because 
    personal accounts use the '/me' endpoint.
    """
    # Personal accounts use /me instead of /users/{email}
    url = f"{GRAPH_API_BASE}/me/messages"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    # Simple formatting logic
    html_body = body.replace("\n", "<br>")
    html_body = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", html_body)

    payload = {
        "subject": subject,
        "body": {
            "contentType": "HTML",
            "content": html_body,
        },
        "toRecipients": [
            {"emailAddress": {"address": to}}
        ],
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
        The following data is now available in shared memory:
        TRANSCRIPT (memory key: meeting:transcript):
        {transcript}

        Please review this and confirm it is valid.
        Then create a summary of the transcript and write the summary to memory key 'transcript:summary'.
        Then extract any needed tasks or todos that should be completed by employees and write this to 'transcript:tasks'.
        Finally set 'workflow:status' to "task" to signal the pipeline is ready to proceed.

        You should respond with only the raw json file for the tasks and summary.
    """

    # get response
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
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
    # print("Transcript Agent summary: \n", summary)
    # print("Transcript Agent tasks: \n", tasks)

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
    instructions     = load_agent("tool_agent.md")
    email_drafts_raw = retrieve_memory("email:drafts", NAMESPACE)

    if not email_drafts_raw:
        raise ValueError("Tool Agent: email:drafts not found in memory — aborting.")

    email_drafts = json.loads(email_drafts_raw) if isinstance(email_drafts_raw, str) else email_drafts_raw

    token          = get_graph_token()
    sender_email   = os.environ.get("OUTLOOK_SENDER_EMAIL")
    if not sender_email:
        raise EnvironmentError("Missing OUTLOOK_SENDER_EMAIL environment variable")

    tools = [
        {
            "name": "create_outlook_draft",
            "description": (
                "Creates a single draft email in the sender's Outlook Drafts folder "
                "via Microsoft Graph API. Does not send the email. Call this once per email."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line"
                    },
                    "body": {
                        "type": "string",
                        "description": "Full email body text"
                    },
                    "type": {
                        "type": "string",
                        "enum": ["task_assignment", "meeting_followup"],
                        "description": "Category of the email"
                    }
                },
                "required": ["to", "subject", "body", "type"]
            }
        }
    ]

    messages = [
        {
            "role": "user",
            "content": f"""
                Here are the email drafts to create in Outlook:
                {json.dumps(email_drafts, indent=2)}

                Use the create_outlook_draft tool to create an Outlook draft for every
                email in both the task_emails and meeting_emails arrays.
                Call the tool once per email — do not batch them together.
                After all drafts are created, provide a brief summary of what was created.
            """
        }
    ]

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=instructions,
        tools=tools,
        messages=messages
    )

    results = []

    while response.stop_reason == "tool_use":
        tool_use_blocks = [
            block for block in response.content
            if block.type == "tool_use"
        ]

        messages.append({
            "role": "assistant",
            "content": response.content
        })

        tool_results = []
        for block in tool_use_blocks:
            try:
                draft = create_outlook_draft(
                    token=token,
                    to=block.input["to"],
                    subject=block.input["subject"],
                    body=block.input["body"]
                )
                result = {
                    "to":               block.input["to"],
                    "subject":          block.input["subject"],
                    "type":             block.input.get("type"),
                    "outlook_draft_id": draft.get("id"),
                    "status":           "success",
                    "error":            None
                }
                print(f"Draft created → {block.input['to']}")
            except requests.HTTPError as e:
                result = {
                    "to":               block.input["to"],
                    "subject":          block.input["subject"],
                    "type":             block.input.get("type"),
                    "outlook_draft_id": None,
                    "status":           "failed",
                    "error":            str(e)
                }
                print(f"Failed → {block.input['to']} — {e}")

            results.append(result)

            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": block.id,
                "content":     json.dumps(result)
            })

        messages.append({
            "role": "user",
            "content": tool_results
        })

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=instructions,
            tools=tools,
            messages=messages
        )

    # --- Store results ---
    report = {
        "drafts_created":  results,
        "total_attempted": len(results),
        "total_succeeded": sum(1 for r in results if r["status"] == "success"),
        "total_failed":    sum(1 for r in results if r["status"] == "failed"),
    }

    store_memory("tool:results", json.dumps(report), NAMESPACE)

    final_text = next(
        (block.text for block in response.content if hasattr(block, "text")), 
        "No summary provided."
    )
    print("Tool Agent summary:", final_text)
    print("Tool Agent report:\n", json.dumps(report, indent=2))

    return report

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
    print("### Successfully validated transcript and employee information ###\n\n\n")
    
    print("### Running Planner agent ###")
    run_planner_agent(client)
    if not validate_memory_key("workflow:plan", NAMESPACE):
        raise ValueError("workflow:plan not found in memory")
    print("### Completed Planner agent ###\n\n\n")
    
    print("### Running Transcript agent ###")
    run_transcript_agent(client)
    if not validate_memory_key("transcript:summary", NAMESPACE):
        raise ValueError("transcript:summary not found in memory")
    if not validate_memory_key("transcript:tasks", NAMESPACE):
        raise ValueError("transcript:tasks not found in memory")
    print("### Completed Transcript agent ###\n\n\n")

    print("### Running Task agent ###")
    run_task_agent(client)
    if not validate_memory_key("task:assignments", NAMESPACE):
        raise ValueError("task:assignments not found in memory")
    print("### Completed Task agent ###\n\n\n")

    print("### Running email agent ###")
    run_email_agent(client)
    if not validate_memory_key("email:drafts", NAMESPACE):
        raise ValueError("email:drafts not found in memory")
    print("### Completed Email agent ###\n\n\n")
    
    # print("### Running Tool agent ###")
    # run_tool_agent(client)
    # if not validate_memory_key("tool:results", NAMESPACE):
    #     raise ValueError("tool:results not found in memory")
    # print("### Completed Tool agent ###\n\n\n")

    summary     = retrieve_memory("transcript:summary", NAMESPACE)
    tasks       = retrieve_memory("transcript:tasks",   NAMESPACE)
    assignments = retrieve_memory("task:assignments",   NAMESPACE)
    emails      = retrieve_memory("email:drafts",       NAMESPACE)
    # tool_results = retrieve_memory("tool:results",      NAMESPACE)
    # print("tool_results: ", tool_results)
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
    
