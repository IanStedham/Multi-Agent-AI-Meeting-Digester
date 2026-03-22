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
    pass

def run_email_agent(client: anthropic.Anthropic):
    pass

def start_workflow(
    client: anthropic.Anthropic,
    transcript_path: Path,
    employee_path: Path
):
    pass