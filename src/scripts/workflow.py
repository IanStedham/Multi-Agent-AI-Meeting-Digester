import anthropic
from pathlib import Path
import subprocess
from memory_management import store_memory, retrieve_memory, validate_memory_key
import json


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
    # load files
    instructions = load_agent("planner_agent.md")

    transcript = retrieve_memory("meeting:transcript", NAMESPACE)
    roster = retrieve_memory("meeting:employees", NAMESPACE)

    # create user message, might need to alter these signals for consistency
    # also i am yet to test if the agent is able to write to the mcp server itself, might be reductive to have in prompt
    user_message = f"""
        The following data is now available in shared memory:
        TRANSCRIPT (memory key: meeting:transcript):
        {transcript}

        EMPLOYEE ROSTER (memory key: meeting:employees):
        {roster}

        Please review both and confirm they are valid.
        Write your workflow plan to memory key 'workflow:plan'.
        Then set 'workflow:status' to "transcript" to signal the pipeline is ready to proceed.
    """

    # get response
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=instructions,
        messages=[{"role": "user", "content": user_message}]
    )

    # set memory in mcp
    plan = response.content[0].text
    store_memory("workflow:plan", plan, NAMESPACE)
    store_memory("workflow:status", "transcript", NAMESPACE)


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
    """

    # get response
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=instructions,
        messages=[{"role": "user", "content": user_message}]
    )

    # set memory in mcp
    response = response.content[0].text.strip()
    print("This is the transcript response: ", response)
    parsed_response = json.loads(response)

    # may need to validate these are not empty and strings
    summary = parsed_response.get("summary", "")
    tasks = parsed_response.get("tasks",   [])

    store_memory("transcript:summary", summary, NAMESPACE)
    store_memory("transcript:tasks", tasks, NAMESPACE)
    store_memory("workflow:status", "task", NAMESPACE)

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
    task_assignments = response.content[0].text
    store_memory("task:assignments", task_assignments, NAMESPACE)
    store_memory("workflow:status", "email", NAMESPACE)
 
    print("Task Agent complete — assignments written to memory.")

    # i dont think this return is needed since we are only accessing info through the mcp server
    # return task_assignments


# this is going to need to be updated to check if the planner agent determined a follow up email needs to be sent
def run_email_agent(client: anthropic.Anthropic):
    # 1. Load agent instructions from Email_agent.md
    agent_instructions = load_agent("email_agent.md")
 
    # 2. Pull required inputs from shared memory
    task_assignments = retrieve_memory("task:assignments", NAMESPACE)
    transcript_summary = retrieve_memory("transcript:summary", NAMESPACE)
 
    # 3. Validate inputs before proceeding
    if not task_assignments or not transcript_summary:
        raise ValueError("Email Agent: Missing required memory keys — aborting.")
 
    # 4. Build the prompt for the agent
    prompt = f"""
    Here are the task assignments:
    {task_assignments}
 
    Here is the meeting summary:
    {transcript_summary}
 
    Draft a professional follow-up email for each employee based on their assigned tasks.
    Return the emails in plain text, clearly separated by employee name.
    """
 
    # 5. Call the Claude API
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=agent_instructions,
        messages=[{"role": "user", "content": prompt}]
    )
 
    # 6. Extract and store the result
    # how will this be structured? is it multiple emails in the one json or several elements for all the drafts?
    draft_emails = response.content[0].text
    store_memory("email:drafts", draft_emails, NAMESPACE)
    store_memory("workflow:status", "tool", NAMESPACE)
 
    print("Email Agent complete — draft emails written to memory.")
    # i dont think this return is needed since we are only accessing info through the mcp server
    #return draft_emails


# NOT YET TESTED, NEED ALL AGENTS READY BEFORE TEST
def start_workflow(
    client: anthropic.Anthropic,
    transcript_path: Path=None,
    employee_path: Path=None
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
    print("### Successfully validated transcript and employee information ###")
    
    print("### Running Planner agent ###")
    run_planner_agent(client)
    if not validate_memory_key("workflow:plan", NAMESPACE):
        raise ValueError("workflow:plan not found in memory")
    if not validate_memory_key("workflow:status", NAMESPACE):
        raise ValueError("workflow:status not found in memory")
    print("### Completed Planner agent ###")
    
    print("### Running Transcript agent ###")
    run_transcript_agent(client)
    if not validate_memory_key("transcript:summary", NAMESPACE):
        raise ValueError("transcript:summary not found in memory")
    if not validate_memory_key("transcript:tasks", NAMESPACE):
        raise ValueError("transcript:tasks not found in memory")
    print("### Completed Transcript agent ###")

    print("### Running Task agent ###")
    run_task_agent(client)
    if not validate_memory_key("task:assignments", NAMESPACE):
        raise ValueError("task:assignments not found in memory")
    print("### Completed planner agent ###")

    print("### Running email agent ###")
    run_email_agent(client)
    if not validate_memory_key("email:drafts", NAMESPACE):
        raise ValueError("email:drafts not found in memory")
    print("### Completed Email agent ###")
    
    # will need this
    # run_tools_agent()