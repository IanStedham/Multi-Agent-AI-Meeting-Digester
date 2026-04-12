import anthropic
from pathlib import Path
import subprocess
from memory_management import store_memory, retrieve_memory, validate_memory_key
import json
import re


"""
Some current problems with this script we should talk through and fix:
1. Parsing the result into summary and transcript in Transcript Agent correctly, can do during testing
2. Email and Task agent currently insert their instructions into the user prompt, I do not think this is needed
    since it is doubling the instructions already given to the agent.
3. Validate the task format in the Task Agent.
4. We may need to adjust token amounts per agent, I am specifically thinking of Email and Transcript Agents
"""


NAMESPACE = "meeting-digester"

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
 


# NOT YET TESTED, NEED ALL AGENTS READY BEFORE TEST
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
    
    # will need this
    # run_tools_agent()

    summary = retrieve_memory("transcript:summary", NAMESPACE)
    tasks = retrieve_memory("transcript:tasks", NAMESPACE)
    assignments = retrieve_memory("task:assignments", NAMESPACE)
    emails = retrieve_memory("email:drafts", NAMESPACE)
    return summary, tasks, assignments, emails
