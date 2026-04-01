import subprocess
from typing import Optional
import shutil

CLAUDE_FLOW = shutil.which("ruflo")
NAMESPACE = "meeting-digester"

"""
Things to consider:
1. Might need to alter storing method in order to handle jsons and txt files
"""

def _run_memory_command(args: list[str], timeout: int = 60, input_text: str = None) -> tuple[bool, str]:
    if CLAUDE_FLOW is None:
        return False, "Ruflo is not installed"

    command = [CLAUDE_FLOW, "memory"] + args

    try:
        result = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0:
            if "[OK]" in stdout or "stored successfully" in stdout.lower():
                return True, stdout

            error_msg = stderr or stdout
            real_errors = [
                line for line in error_msg.splitlines()
                if "EACCES" not in line
                and "@xenova" not in line
                and "async" not in line
                and line.strip()
            ]
            clean_error = "\n".join(real_errors[:3])
            return False, f"Ruflo memory command failed: {clean_error}"

        return True, stdout

    # below is claude generated code to help with error catching i was struggling with
    except subprocess.TimeoutExpired:
        return False, (
            f"Ruflo memory command timed out after {timeout} seconds.\n"
            f"Command was: {' '.join(command)}"
        )

    except FileNotFoundError:
        return False, (
            f"Could not execute ruflo at: {CLAUDE_FLOW}\n"
            f"Try running 'which ruflo' in your terminal to verify the path."
        )

    except Exception as e:
        return False, f"Unexpected error running Ruflo CLI: {e}"


def store_memory(key: str, value: str, namespace: str) -> bool:
    import time

    if not key or not key.strip():
        print("[MEMORY ERROR] store_memory called with an empty key.")
        return False

    if value is None:
        print(f"[MEMORY ERROR] store_memory called with None value for key: {key}")
        return False

    _run_memory_command(
        ["delete", "--key", key, "--namespace", namespace],
        input_text="Yes\n"
    )

    time.sleep(1.0)

    retries = 3
    for attempt in range(retries):
        success, output = _run_memory_command([
            "store",
            "--key",       key,
            "--value",     value,
            "--namespace", namespace
        ])

        if success:
            return True

        if "UNIQUE constraint" in output:
            if attempt < retries - 1:
                time.sleep(1.0 * (attempt + 1))
                continue

        print(f"[MEMORY ERROR] Failed to store key '{key}': {output}")
        return False

    print(f"[MEMORY ERROR] Failed to store key '{key}' after {retries} attempts")
    return False


def retrieve_memory(key: str, namespace: str) -> Optional[str]:
    if not key or not key.strip():
        print("[MEMORY ERROR] retrieve_memory called with an empty key.")
        return None

    success, output = _run_memory_command([
        "retrieve",
        "--key",       key,
        "--namespace", namespace
    ])

    if not success:
        return None

    lines = output.splitlines()
    value_lines = []
    capturing = False

    for line in lines:
        if "| Value:" in line:
            capturing = True
            continue
        if capturing:
            if line.startswith("+"):
                break
            cleaned = line.strip().strip("|").strip()
            if cleaned:
                value_lines.append(cleaned)

    if value_lines:
        return "\n".join(value_lines)

    return None


def validate_memory_key(key: str, namespace: str) -> bool:
    value = retrieve_memory(key, namespace)
    return value is not None and value.strip() != ""


def delete_memory(key: str, namespace: str) -> bool:
    if not key or not key.strip():
        print("[MEMORY ERROR] delete_memory called with an empty key.")
        return False

    success, output = _run_memory_command(
        [
            "delete",
            "--key",       key,
            "--namespace", namespace
        ],
        input_text="Yes\n"
    )

    if not success:
        print(f"[MEMORY WARNING] Could not delete key '{key}': {output}")
        return False

    return True


def list_memory_keys(namespace: str = "workflow") -> list[str]:
    success, output = _run_memory_command([
        "list",
        "--namespace", namespace
    ])

    if not success or not output:
        return []

    keys = []
    lines = output.splitlines()
    
    for line in lines:
        if not line.startswith("|"):
            continue
        
        columns = line.split("|")
        
        if len(columns) < 3:
            continue
        
        key = columns[1].strip()

        if key == "Key" or not key:
            continue
        
        keys.append(key)
    
    return keys


def clear_workflow_memory():
    keys_to_clear = [
        "meeting:transcript",
        "meeting:employees",
        "workflow:plan",
        "workflow:status",
        "transcript:summary",
        "transcript:tasks",
        "task:assignments",
        "email:drafts",
    ]

    print("Clearing previous workflow memory...")
    cleared = 0
    for key in keys_to_clear:
        if validate_memory_key(key, NAMESPACE):
            success = delete_memory(key, NAMESPACE)
            if success:
                cleared += 1

    print(f"Successfully cleared {cleared}/8 key from shared memory.")