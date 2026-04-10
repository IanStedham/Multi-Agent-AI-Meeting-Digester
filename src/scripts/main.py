import argparse
import os
import sys
from pathlib import Path
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
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = f.read().strip()

    with open(employee_path, "r", encoding="utf-8") as f:
        employees = f.read().strip()

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

    transcript_path = "src/data_layer/extractive_txt/ES2002a.txt"
    employee_path = "src/data_layer/employee_json/employee_es.json"
    load_inputs_to_memory(transcript_path, employee_path)

    start_workflow(
        client=client,
        transcript_path=transcript_path,
        employee_path=employee_path
    )

if __name__ == "__main__":
    main()
