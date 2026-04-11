import subprocess
from typing import Optional, Any, List, Tuple
import shutil
import json
import time
import os


# WSL PATH CLARIFICATION:
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLAUDE_FLOW = "/usr/bin/ruflo" if os.path.exists("/usr/bin/ruflo") else shutil.which("ruflo")
NAMESPACE = "meeting-digester"

def _run_memory_command(args: list[str], input_text: str = None) -> Tuple[int, str, str]:
    """
    Enhanced helper that FORCES the command to run in the project root.
    This ensures Ruflo always sees the local .swarm/memory.db.
    """
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
            cwd=PROJECT_ROOT  # <-- CRITICAL: Forces local context
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return 1, "", str(e)

def clear_workflow_memory():
    """
    Strict Local Wipe: Only targets the project-specific database.
    """
    print(f"Purging LOCAL memory only...")
    
    # 1. Kill processes
    try:
        subprocess.run(["pkill", "-9", "-f", "ruflo"], capture_output=True)
    except:
        pass
        
    # 2. Target the local DB specifically
    local_db = os.path.join(PROJECT_ROOT, ".swarm", "memory.db")
    if os.path.exists(local_db):
        os.remove(local_db)
        print(f"✅ Local DB Deleted: {local_db}")

    # 3. Re-init in the project root
    _run_memory_command(["init"])

def run_health_check():
    print(f"\n--- RUFLO BINARY HEALTH CHECK ---")
    if not CLAUDE_FLOW:
        print("Binary not found.")
        return
    
    if os.path.islink(CLAUDE_FLOW):
        print(f"🔗 Symlink points to: {os.path.realpath(CLAUDE_FLOW)}")
    
    res = subprocess.run([CLAUDE_FLOW, "--version"], capture_output=True, text=True)
    print(f"Version output: {res.stdout.strip() or res.stderr.strip()}")
    print(f"----------------------------------\n")

def force_kill_ruflo():
    try:
        subprocess.run(["pkill", "-9", "-f", "ruflo"], capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "node"], capture_output=True)
        time.sleep(0.5)
    except:
        pass

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
                print(f"   ⚠️ Could not create directory {p}: {e}")


def store_memory(key: str, value: Any, namespace: str = NAMESPACE) -> bool:
    """Stores data with auto-initialization if the database is missing."""
    _ensure_directories()
    
    _run_memory_command(["delete", "--key", key, "--namespace", namespace], input_text="Yes\n")
    val_str = json.dumps(value) if not isinstance(value, str) else value
    code, out, err = _run_memory_command(["store", "--key", key, "--value", val_str, "--namespace", namespace])
    
    if code != 0 and "Database not initialized" in err:
        print(f"   [Diagnosis] Database not initialized. Running init...")
        _run_memory_command(["init"])
        code, out, err = _run_memory_command(["store", "--key", key, "--value", val_str, "--namespace", namespace])

    if code != 0:
        print(f"\nRUFLO STORE FAILURE for key '{key}':")
        print(f"Exit Code: {code}")
        print(f"Stderr: {err}")
        print(f"Stdout: {out}")
        
        if "UNIQUE" in (err or out):
            print(f"   [Diagnosis] Collision detected. Attempting emergency retry...")
            time.sleep(1)
            _run_memory_command(["delete", "--key", key, "--namespace", namespace], input_text="Yes\n")
            code2, out2, err2 = _run_memory_command(["store", "--key", key, "--value", val_str, "--namespace", namespace])
            return code2 == 0
            
        return False
    return True

def retrieve_memory(key: str, namespace: str = NAMESPACE) -> Optional[str]:
    code, out, err = _run_memory_command(["retrieve", "--key", key, "--namespace", namespace])
    if code != 0 or not out:
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