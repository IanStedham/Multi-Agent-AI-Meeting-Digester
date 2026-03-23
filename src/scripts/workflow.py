import anthropic
from pathlib import Path
import subprocess
import workflow

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
    agent_path = Path(f"src/agents/{agent_filename}")
    if not agent_path.exists():
        raise FileNotFoundError(
            f"File not found: {agent_path}"
        )
    return agent_path.read_text(encoding="utf-8")

def initialise_swarm():
    try:
        result = subprocess.run(
            [
                "npx", "@claude-flow/cli@latest",
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
        print("      [WARNING] Swarm init timed out. Continuing anyway.")
    except FileNotFoundError:
        print("      [WARNING] Ruflo CLI not found. Continuing without swarm init.")

# kinda a wrapper for calling agents with passed in markdown file as input
def run_planner_agent(client: anthropic.Anthropic):
    # load files
    instructions = load_agent("planner_agent.md")

    transcript   = workflow.retrieve_memory("meeting:transcript")
    roster       = workflow.retrieve_memory("employees:roster")

    # create user message
    user_message = f"""
        The following data is now available in shared memory:
        TRANSCRIPT (memory key: meeting:transcript):
        {transcript}

        EMPLOYEE ROSTER (memory key: employees:roster):
        {roster}

        Please review both, confirm they are valid, write your workflow
        plan to memory key `workflow:plan`, and set `workflow:status`
        to "dissecting transcript" to signal the pipeline is ready to proceed.
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
    workflow.store_memory("workflow:plan", plan)
    workflow.store_memory("workflow:status", "dissect transcript")


def run_transcript_agent(client: anthropic.Anthropic):
    pass

def run_task_agent(client: anthropic.Anthropic):
     """
    Loads the Task Assigning Agen
    
    t instructions, retrieves task list
    and employee info from shared memory, then assigns tasks with deadlines.
    """
    # 1. Load agent instructions from Task_agent.md
    agent_instructions = load_agents("Task_agent.md")
 
    # 2. Pull required inputs from shared memory
    transcript_tasks = memory_search("transcript_tasks")
    employee_information = memory_search("employee_information")
 
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
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
 
    # 6. Extract and store the result
    task_assignments = response.content[0].text
    memory_store("task_assignments", task_assignments)
    memory_store("workflow_status", "task_agent_complete")
 
    print("Task Agent complete — assignments written to memory.")
    return task_assignments

def run_email_agent(client: anthropic.Anthropic):
    """
    Loads the Email Agent instructions, retrieves task assignments
    and transcript summary from shared memory, then drafts emails.
    """
    # 1. Load agent instructions from Email_agent.md
    agent_instructions = load_agents("Email_agent.md")
 
    # 2. Pull required inputs from shared memory
    task_assignments = memory_search("task_assignments")
    transcript_summary = memory_search("transcript_summary")
 
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
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
 
    # 6. Extract and store the result
    draft_emails = response.content[0].text
    memory_store("draft_emails", draft_emails)
    memory_store("workflow_status", "email_agent_complete")
 
    print("Email Agent complete — draft emails written to memory.")
    return draft_emails

def start_workflow(
    client: anthropic.Anthropic,
    transcript_path: Path,
    employee_path: Path
):
    pass