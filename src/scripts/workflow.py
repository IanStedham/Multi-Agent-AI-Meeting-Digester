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


def get_graph_token() -> str:
    tenant_id     = os.environ.get("AZURE_TENANT_ID")
    client_id     = os.environ.get("AZURE_CLIENT_ID")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET")

    if not all([tenant_id, client_id, client_secret]):
        raise EnvironmentError(
            "Missing one or more required environment variables: "
            "AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET"
        )

    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    payload = {
        "grant_type":    "client_credentials",
        "client_id":     client_id,
        "client_secret": client_secret,
        "scope":         "https://graph.microsoft.com/.default",
    }

    response = requests.post(url, data=payload)
    response.raise_for_status()
    return response.json()["access_token"]

def create_outlook_draft(token: str, user_email: str, to: str, subject: str, body: str) -> dict:
    url = f"{GRAPH_API_BASE}/users/{user_email}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    html_body = body.replace("\n", "<br>")
    html_body = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", html_body)

    payload = {
        "subject": subject,
        "body": {
            "contentType": "HTML",   # changed from Text
            "content":     html_body,
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

    response = response.content[0].text.strip()
    response = re.sub(r"^```(?:json)?\s*", "", response)
    response = re.sub(r"\s*```$", "", response)
    response = response.strip()
    plan = json.loads(response)
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
    print("Transcript Agent raw response:\n", response)
    # response = response.content[0].text.strip()
    # parsed_response = json.loads(response)
    response = response.content[0].text.strip()
    response = re.sub(r"^```(?:json)?\s*", "", response)
    response = re.sub(r"\s*```$", "", response)
    response = response.strip()
    parsed_response = json.loads(response)
    print("Transcript Agent format response:\n", response)

    # may need to validate these are not empty and strings
    summary = parsed_response.get("summary", "")
    tasks = parsed_response.get("tasks",   [])
    print("Transcript Agent summary: ", summary)
    print("Transcript Agent tasks: ", tasks)

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
    print("Task Agent raw response:\n", response)
    task_assignments = response.content[0].text
    task_assignments = re.sub(r"^```(?:json)?\s*", "", task_assignments)
    task_assignments = re.sub(r"\s*```$", "", task_assignments)
    task_assignments = task_assignments.strip()
    parsed_task_assignments = json.loads(task_assignments)
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

    print("Email Agent raw respone:\n", response)
    draft_emails = response.content[0].text
    draft_emails = re.sub(r"^```(?:json)?\s*", "", draft_emails)
    draft_emails = re.sub(r"\s*```$", "", draft_emails)
    draft_emails = draft_emails.strip()
    parsed_draft_emails = json.loads(draft_emails)
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
                    user_email=sender_email,
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
    print("### Completed planner agent ###\n\n\n")

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
