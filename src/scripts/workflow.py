import anthropic
from pathlib import Path
import subprocess
from memory_management import store_memory, retrieve_memory, validate_memory_key
import json

def main():
    # 1. Initialize the Ruflo swarm at the start of the workflow
    # 2. Call the Tools Agent to load inputs into shared memory
    # 3. Call the Planner Agent to set up the workflow plan
    # 4. Call the Dissector Agent to extract tasks from the transcript
    # 5. Call the Assigner Agent to match tasks to employees
    # 6. Call the Emailer Agent to draft follow-up emails
    # 7. Call the Tools Agent again to write final outputs to disk
    # 8. Validate memory between each step so nothing proceeds on bad data
    # 9. Update workflow status in shared memory at each stage
    # 10. Handle agent-level errors and report them clearly
    pass

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

    transcript = retrieve_memory("meeting:transcript")
    roster = retrieve_memory("meeting:employees")

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
    store_memory("workflow:plan", plan)
    store_memory("workflow:status", "transcript")


def run_transcript_agent(client: anthropic.Anthropic):
    # load files
    instructions = load_agent("transcript_agent.md")

    transcript = retrieve_memory("meeting:transcript")

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
    # i need to figure out how to parse the reponse once we have data for testing
    response = response.content[0].text

    summary = ""
    tasks = {}
    store_memory("transcript:summary", summary)
    store_memory("transcript:tasks", tasks)
    store_memory("workflow:status", "task")

def run_task_agent(client: anthropic.Anthropic):
    """
    Loads the Task Assigning Agen
    
    t instructions, retrieves task list
    and employee info from shared memory, then assigns tasks with deadlines.
    """
    # 1. Load agent instructions from Task_agent.md
    agent_instructions = load_agent("task_agent.md")
 
    # 2. Pull required inputs from shared memory
    transcript_tasks = retrieve_memory("transcript:tasks")
    employee_information = retrieve_memory("meeting:employees")
 
    # 3. Validate inputs before proceeding
    if not transcript_tasks or not employee_information:
        raise ValueError("Task Agent: Missing required memory keys — aborting.")
 
    # 4. Build the prompt for the agent
    prompt = f"""
    {agent_instructions}
 
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
        messages=[{"role": "user", "content": prompt}]
    )
 
    # 6. Extract and store the result
    task_assignments = response.content[0].text
    store_memory("task:assignments", task_assignments)
    store_memory("workflow:status", "email")
 
    print("Task Agent complete — assignments written to memory.")

    # i dont think this return is needed since we are only accessing info through the mcp server
    # return task_assignments


# this is going to need to be updated to check if the planner agent determined a follow up email needs to be sent
def run_email_agent(client: anthropic.Anthropic):
    """
    Loads the Email Agent instructions, retrieves task assignments
    and transcript summary from shared memory, then drafts emails.
    """
    # 1. Load agent instructions from Email_agent.md
    agent_instructions = load_agent("email_agent.md")
 
    # 2. Pull required inputs from shared memory
    task_assignments = retrieve_memory("task:assignments")
    transcript_summary = retrieve_memory("transcript:summary")
 
    # 3. Validate inputs before proceeding
    if not task_assignments or not transcript_summary:
        raise ValueError("Email Agent: Missing required memory keys — aborting.")
 
    # 4. Build the prompt for the agent
    prompt = f"""
    {agent_instructions}
 
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
        messages=[{"role": "user", "content": prompt}]
    )
 
    # 6. Extract and store the result
    # how will this be structured? is it multiple emails in the one json or several elements for all the drafts?
    draft_emails = response.content[0].text
    store_memory("email:drafts", draft_emails)
    store_memory("workflow:status", "tool")
 
    print("Email Agent complete — draft emails written to memory.")
    # i dont think this return is needed since we are only accessing info through the mcp server
    #return draft_emails


# NOT YET TESTED, NEED ALL AGENTS READY BEFORE TEST
def start_workflow(
    client: anthropic.Anthropic,
    transcript_path: Path,
    employee_path: Path
):
    # initialize the the swarm
    initialise_swarm()

    # will need this when ready
    # run_tools_agent()

    # validate the transcript and the employee roster are ready
    validate_memory_key("meeting:transcript", "Initialize")
    validate_memory_key("meeting:employees",   "Initialize")
    
    run_planner_agent(client)
    validate_memory_key("workflow:plan",   "Planner Agent")
    validate_memory_key("workflow:status", "Planner Agent")
    
    run_transcript_agent(client)
    validate_memory_key("transcript:summary", "Transcript Agent")

    # loading this into a json object for testing, wont need this in the end
    tasks_json = validate_memory_key("transcript:tasks", "Transcript Agent")
    tasks = json.loads(tasks_json)

    print("TASKS")
    print("tasks_json: ", tasks_json)
    print("tasks: ", tasks)


    run_task_agent(client)
    # also just loading this for testing
    assigned_json  = validate_memory_key("task:assignments", "Task Agent")
    assigned_tasks = json.loads(assigned_json)
    
    print("ASSIGNED TASKS")
    print("assigned_json: ", assigned_json)
    print("assigned_tasks: ", assigned_tasks)


    run_email_agent(client)
    # this is just for testing, this will need to be corrected when i know how emails are structured
    emails_json = validate_memory_key("email:drafts", "Email Agent")
    emails      = json.loads(emails_json)
    email_count = len(emails.get("individual_emails", []))

    print("EMAILS")
    print("emails_json: ", emails_json)
    print("emails: ", emails)
    print("email_count: ", email_count)
    
    # will need this
    # run_tools_agent()