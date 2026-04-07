import argparse
import os
import sys
from pathlib import Path
<<<<<<< Updated upstream
from dotenv import load_dotenv
import anthropic
from workflow import start_workflow
from memory_management import store_memory, clear_workflow_memory

NAMESPACE = "meeting-digester"

def validate_environment() -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("\nANTHROPIC_API_KEY not found\n")
        print("Make sure your .env file contains your API key\n")
        sys.exit(1)
    return api_key
  
def load_inputs_to_memory(transcript_path: Path, employee_path: Path):
    transcript = transcript_path.read_text(encoding="utf-8").strip()
    employees = employee_path.read_text(encoding="utf-8").strip()

    if not store_memory("meeting:transcript", transcript, NAMESPACE):
        print("Failed to store transcript in mcp server")
        sys.exit(1)
    if not store_memory("meeting:employees", employees, NAMESPACE):
        print("Failed to store employee data in mcp server")
        sys.exit(1)

def main():
    load_dotenv()

    api_key = validate_environment()
    client = anthropic.Anthropic(api_key=api_key)
    clear_workflow_memory()

    transcript_path = "../data_layer/transcript.txt"
    employee_path = "../data_layer/employee_information.json"
    load_inputs_to_memory(transcript_path, employee_path)

    start_workflow(
        client=client,
        transcript_path=transcript_path,
        employee_path=employee_path
    )

if __name__ == "__main__":
    main()
=======

import anthropic
from dotenv import load_dotenv


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _scripts_dir() -> Path:
    return Path(__file__).resolve().parent


def main() -> None:
    load_dotenv(_project_root() / ".env")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not api_key.strip():
        print("ERROR: ANTHROPIC_API_KEY is not set (check .env).", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Load transcript and roster into memory and run the meeting digest workflow."
    )
    parser.add_argument(
        "-t",
        "--transcript",
        type=Path,
        required=True,
        help="Path to the meeting transcript file",
    )
    parser.add_argument(
        "-e",
        "--employees",
        type=Path,
        required=True,
        help="Path to the employee roster file (text or JSON as used by your agents)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for written outputs (default: <project>/outputs)",
    )
    args = parser.parse_args()

    transcript_path = args.transcript.resolve()
    employee_path = args.employees.resolve()

    if not transcript_path.is_file():
        print(f"ERROR: Transcript file not found: {transcript_path}", file=sys.stderr)
        sys.exit(1)
    if not employee_path.is_file():
        print(f"ERROR: Employee roster file not found: {employee_path}", file=sys.stderr)
        sys.exit(1)

    sd = _scripts_dir()
    if str(sd) not in sys.path:
        sys.path.insert(0, str(sd))

    from memory_management import (  # noqa: PLC0415
        clear_workflow_memory,
        retrieve_memory,
        store_memory,
    )
    from workflow import MEMORY_NS, start_workflow  # noqa: PLC0415

    clear_workflow_memory()

    transcript_text = transcript_path.read_text(encoding="utf-8")
    roster_text = employee_path.read_text(encoding="utf-8")

    if not store_memory("meeting:transcript", transcript_text, MEMORY_NS):
        print("ERROR: Failed to store meeting:transcript in shared memory.", file=sys.stderr)
        sys.exit(1)
    if not store_memory("employees:roster", roster_text, MEMORY_NS):
        print("ERROR: Failed to store employees:roster in shared memory.", file=sys.stderr)
        sys.exit(1)

    out_dir = (args.output_dir or (_project_root() / "outputs")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        start_workflow(client, transcript_path, employee_path)
    except Exception as exc:
        print(f"ERROR: Workflow failed: {exc}", file=sys.stderr)
        sys.exit(1)

    drafts = retrieve_memory("emails:drafted", MEMORY_NS)
    summary = retrieve_memory("transcript:summary", MEMORY_NS)

    (out_dir / "draft_emails.txt").write_text(drafts or "", encoding="utf-8")
    if summary:
        (out_dir / "transcript_summary.txt").write_text(summary, encoding="utf-8")

    print(f"Wrote outputs under {out_dir}")


if __name__ == "__main__":
    main()
>>>>>>> Stashed changes
