import subprocess
from typing import Optional
import shutil

CLAUDE_FLOW = shutil.which("ruflo")

# this is gonna be a wrapper function for interacting with mcp server, i saw a lot of projects have something like this
def _run_memory_command(args: list[str]) -> tuple[bool, str]:
    if CLAUDE_FLOW is None:
        return False, (
            "ruflo binary not found. "
            "Make sure it is installed with: npm install -g ruflo"
        )

    command = [CLAUDE_FLOW, "memory"] + args

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            return False, f"Ruflo memory command failed: {error_msg}"

        return True, result.stdout.strip()

    except subprocess.TimeoutExpired:
        return False, (
            f"Ruflo memory command timed out after 15 seconds.\n"
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
    if not key or not key.strip():
        print("[MEMORY ERROR] store_memory called with an empty key.")
        return False

    if value is None:
        print(f"[MEMORY ERROR] store_memory called with None value for key: {key}")
        return False

    success, output = _run_memory_command([
        "store",
        "--key",       key,
        "--value",     value,
        "--namespace", namespace
    ])

    if not success:
        print(f"[MEMORY ERROR] Failed to store key '{key}': {output}")
        return False

    return True

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
        # Not necessarily an error — key might just not exist yet
        return None

    if not output:
        return None

    return output

def validate_memory_key(key: str, namespace: str) -> bool:
    value = retrieve_memory(key, namespace)
    return value is not None and value.strip() != ""

def delete_memory(key: str, namespace: str) -> bool:
    if not key or not key.strip():
        print("[MEMORY ERROR] delete_memory called with an empty key.")
        return False

    success, output = _run_memory_command([
        "delete",
        "--key",       key,
        "--namespace", namespace
    ])
    

    if not success:
        print(f"[MEMORY WARNING] Could not delete key '{key}': {output}")
        return False

    return True

# maybe a function like this isnt needed, just saw a lot of projects with it
def list_memory_keys(namespace: str) -> list[str]:
   success, output = _run_memory_command(["list", "--namespace", namespace])
   
   if not success or not output:
        return []
   
   keys = [line.strip() for line in output.splitlines() if line.strip()]
   return keys


def clear_workflow_memory():
    # might need to edit
    keys_to_clear = [
        "meeting:transcript",
        "employees:roster",
        "workflow:plan",
        "workflow:status",
        "meeting:raw_tasks",
        "meeting:assigned_tasks",
        "emails:drafted",
    ]

    print("Clearing previous workflow memory...")
    cleared = 0
    for key in keys_to_clear:
        if validate_memory_key(key):
            success = delete_memory(key)
            if success:
                cleared += 1

    print(f"      Cleared {cleared} key(s) from shared memory.")