import subprocess
from typing import Optional, Any, List, Tuple
import shutil
import json
import time
import os
import platform


IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "LINUX"
CLAUDE_FLOW = shutil.which("ruflo")
NAMESPACE = "meeting-digester"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _run_memory_command(args: list[str], input_text: str = None) -> Tuple[int, str, str]:
    if not CLAUDE_FLOW:
        return 1, "", "Ruflo binary not found"
    
    command = [CLAUDE_FLOW, "memory"] + args
    try:
        result = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=25,
            cwd=PROJECT_ROOT
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return 1, "", str(e)

def clear_workflow_memory():
    print("Resetting Local Memory: ", NAMESPACE)
    
    local_db = os.path.join(PROJECT_ROOT, ".swarm", "memory.db")
    if os.path.exists(local_db):
        success = False
        for attempt in range(3):
            try:
                os.remove(local_db)
                print("Physically deleted local database")
                success = True
                break
            except PermissionError:
                print("Database locked, clearing processes. Attempt ", attempt)
                force_kill_ruflo()
                time.sleep(0.5)
            except Exception as e:
                print("Unexpected error during deletion: ", {e})
                break
        
        if not success:
            print("Failed to clear database. Please close any programs using the memory file.")

    # Always re-init to ensure tables are ready
    _run_memory_command(["init"])
    print("Local environment initialized.")

def run_health_check():
    print("\n--- RUFLO BINARY HEALTH CHECK ---")
    if not CLAUDE_FLOW:
        print("Binary not found.")
        return
    
    if os.path.islink(CLAUDE_FLOW):
        print("Symlink points to: ", os.path.realpath(CLAUDE_FLOW))
    
    res = subprocess.run([CLAUDE_FLOW, "--version"], capture_output=True, text=True)
    print("Version output: ", {res.stdout.strip() or res.stderr.strip()})
    print(f"----------------------------------\n")

def force_kill_ruflo():
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/IM", "node.exe", "/T"], capture_output=True)
        elif IS_LINUX:
            subprocess.run(["pkill", "-9", "-f", "ruflo"], capture_output=True)
        time.sleep(0.3) 
    except:
        return 1, "", "Acceptable OS not found, ensure you are running on Windows or Linux"

def _ensure_directories():
    paths = [
        os.path.expanduser("~/.ruflo"),
        os.path.join(os.getcwd(), ".swarm")
    ]
    for p in paths:
        if not os.path.exists(p):
            try:
                os.makedirs(p, exist_ok=True)
            except Exception as e:
                print("Could not create directory",  p, ":", e)


def store_memory(key: str, value: Any, namespace: str = NAMESPACE) -> bool:
    val_str = json.dumps(value) if not isinstance(value, str) else value
    
    _run_memory_command(["delete", "--key", key, "--namespace", namespace], input_text="Yes\n")
    code, out, err = _run_memory_command(["store", "--key", key, "--value", val_str, "--namespace", namespace])
    
    if code != 0:
        if "not initialized" in err:
            _run_memory_command(["init"])
            code, out, err = _run_memory_command(["store", "--key", key, "--value", val_str, "--namespace", namespace])
        
        if code != 0:
            print("RUFLO STORE ERROR: ", key, ":", (err or out))
            return False
    return True

def retrieve_memory(key: str, namespace: str = NAMESPACE) -> Optional[str]:
    code, out, err = _run_memory_command(["retrieve", "--key", key, "--namespace", namespace])
    if code != 0 or not out or "not found" in out.lower():
        return None

    lines = out.splitlines()
    value_lines = []
    capturing = False
    for line in lines:
        if "| Value:" in line:
            capturing = True
            continue
        if capturing:
            if line.startswith("+"): break
            cleaned = line.strip().strip("|").strip()
            if cleaned:
                value_lines.append(cleaned)
    return "\n".join(value_lines) if value_lines else None

def validate_memory_key(key: str, namespace: str = NAMESPACE) -> bool:
    value = retrieve_memory(key, namespace)
    return value is not None and value.strip() != ""

# Run health check on import
run_health_check()