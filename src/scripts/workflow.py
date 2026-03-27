import anthropic
import json
import re
import subprocess
from pathlib import Path

from memory_management import retrieve_memory, store_memory

MEMORY_NS = "workflow"


def _require_memory(key: str, stage: str) -> str:
    val = retrieve_memory(key, MEMORY_NS)
    if not val or not val.strip():
        raise ValueError(f"{stage}: Missing or empty memory key '{key}'")
    return val


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


def run_planner_agent(client: anthropic.Anthropic):
    instructions = load_agent("planner_agent.md")

    transcript = retrieve_memory("meeting:transcript", MEMORY_NS)
    roster = retrieve_memory("employees:roster", MEMORY_NS)

    user_message = f"""
        The following data is now available in shared memory:
        TRANSCRIPT (memory key: meeting:transcript):
        {transcript}

        EMPLOYEE ROSTER (memory key: employees:roster):
        {roster}

        Please review both and confirm they are valid.
        Write your workflow plan to memory key 'workflow:plan'.
        Then set 'workflow:status' to "transcript" to signal the pipeline is ready to proceed.
    """

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=instructions,
        messages=[{"role": "user", "content": user_message}]
    )

    plan = response.content[0].text
    store_memory("workflow:plan", plan, MEMORY_NS)
    store_memory("workflow:status", "transcript", MEMORY_NS)


def _extract_tasks_json(assistant_text: str) -> tuple[str, str]:
    """Best-effort: summary text and JSON array string for transcript:tasks."""
    summary = assistant_text.split("```")[0].strip() or assistant_text.strip()
    tasks_json = "[]"
    block = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", assistant_text)
    if block:
        try:
            data = json.loads(block.group(1))
            if isinstance(data, list):
                return summary, json.dumps(data)
        except json.JSONDecodeError:
            pass
    bracket = re.search(r"(\[[\s\S]*\])", assistant_text)
    if bracket:
        try:
            data = json.loads(bracket.group(1))
            if isinstance(data, list):
                return summary, json.dumps(data)
        except json.JSONDecodeError:
            pass
    return summary, tasks_json


def run_transcript_agent(client: anthropic.Anthropic):
    instructions = load_agent("transcript_agent.md")

    transcript = retrieve_memory("meeting:transcript", MEMORY_NS)

    user_message = f"""
        The following data is now available in shared memory:
        TRANSCRIPT (memory key: meeting:transcript):
        {transcript}

        Please review this and confirm it is valid.
        Then create a summary of the transcript and write the summary to memory key 'transcript:summary'.
        Then extract any needed tasks or todos that should be completed by employees and write this to 'transcript:tasks'.
        Finally set 'workflow:status' to "task" to signal the pipeline is ready to proceed.
    """

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=instructions,
        messages=[{"role": "user", "content": user_message}]
    )

    assistant_text = response.content[0].text.strip()
    summary, tasks_json = _extract_tasks_json(assistant_text)

    store_memory("transcript:summary", summary, MEMORY_NS)
    store_memory("transcript:tasks", tasks_json, MEMORY_NS)
    store_memory("workflow:status", "task", MEMORY_NS)


def run_task_agent(client: anthropic.Anthropic):
    """
    Loads the Task Assigning Agent instructions, retrieves task list
    and employee info from shared memory, then assigns tasks with deadlines.
    """
    agent_instructions = load_agent("task_agent.md")

    transcript_tasks = retrieve_memory("transcript:tasks", MEMORY_NS)
    employee_information = retrieve_memory("employees:roster", MEMORY_NS)

    if not transcript_tasks or not employee_information:
        raise ValueError("Task Agent: Missing required memory keys — aborting.")

    prompt = f"""
    {agent_instructions}

    Here are the tasks extracted from the transcript:
    {transcript_tasks}

    Here is the employee information:
    {employee_information}

    Assign each task to the appropriate employee with a deadline.
    Return only valid JSON matching the output format in your instructions.
    """

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    task_assignments = response.content[0].text
    store_memory("meeting:assigned_tasks", task_assignments, MEMORY_NS)
    store_memory("workflow:status", "task_agent_complete", MEMORY_NS)

    print("Task Agent complete — assignments written to memory.")
    return task_assignments


def run_email_agent(client: anthropic.Anthropic):
    """
    Loads the Email Agent instructions, retrieves task assignments
    and transcript summary from shared memory, then drafts emails.
    """
    agent_instructions = load_agent("email_agent.md")

    task_assignments = retrieve_memory("meeting:assigned_tasks", MEMORY_NS)
    transcript_summary = retrieve_memory("transcript:summary", MEMORY_NS)

    if not task_assignments or not transcript_summary:
        raise ValueError("Email Agent: Missing required memory keys — aborting.")

    prompt = f"""
    {agent_instructions}

    Here are the task assignments:
    {task_assignments}

    Here is the meeting summary:
    {transcript_summary}

    Draft a professional follow-up email for each employee based on their assigned tasks.
    Return the emails in plain text, clearly separated by employee name.
    """

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    draft_emails = response.content[0].text
    store_memory("emails:drafted", draft_emails, MEMORY_NS)
    store_memory("workflow:status", "email_agent_complete", MEMORY_NS)

    print("Email Agent complete — draft emails written to memory.")
    return draft_emails


def start_workflow(
    client: anthropic.Anthropic,
    transcript_path: Path,
    employee_path: Path
):
    initialise_swarm()

    _require_memory("meeting:transcript", "Initialize")
    _require_memory("employees:roster", "Initialize")

    run_planner_agent(client)
    _require_memory("workflow:plan", "Planner Agent")
    _require_memory("workflow:status", "Planner Agent")

    run_transcript_agent(client)
    tasks_json = _require_memory("transcript:tasks", "Transcript Agent")
    tasks = json.loads(tasks_json)

    print("TASKS")
    print("tasks_json: ", tasks_json)
    print("tasks: ", tasks)

    run_task_agent(client)
    assigned_json = _require_memory("meeting:assigned_tasks", "Task Agent")
    try:
        assigned_tasks = json.loads(assigned_json)
    except json.JSONDecodeError:
        assigned_tasks = {"raw": assigned_json}

    print("ASSIGNED TASKS")
    print("assigned_json: ", assigned_json)
    print("assigned_tasks: ", assigned_tasks)

    run_email_agent(client)
    emails_text = _require_memory("emails:drafted", "Email Agent")
    try:
        emails = json.loads(emails_text)
        email_count = len(emails.get("individual_emails", []))
    except json.JSONDecodeError:
        emails = {"raw_plain_text": emails_text}
        email_count = 1 if emails_text.strip() else 0

    print("EMAILS")
    print("emails_json: ", emails_text)
    print("emails: ", emails)
    print("email_count: ", email_count)
