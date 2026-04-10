import subprocess
from typing import Optional, Any, List, Tuple
import shutil
import json
import time
import os

# WSL PATH CLARIFICATION:
CLAUDE_FLOW = "/usr/bin/ruflo" if os.path.exists("/usr/bin/ruflo") else shutil.which("ruflo")
NAMESPACE = "meeting-digester"

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

def _run_memory_command(args: List[str], input_text: str = None) -> Tuple[int, str, str]:
    if not CLAUDE_FLOW:
        return 1, "", "Ruflo binary not found"
    
    command = [CLAUDE_FLOW, "memory"] + args
    try:
        result = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=25
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return 1, "", str(e)

def clear_workflow_memory():
    print(f"Initiating WSL Triple-Wipe for: {NAMESPACE}")
    force_kill_ruflo()
    
    potential_dbs = [
        os.path.expanduser("~/.ruflo/ruflo.db"),
        os.path.join(os.getcwd(), ".swarm", "memory.db"),
        os.path.join(os.getcwd(), "ruflo.db")
    ]
    
    for db_path in potential_dbs:
        if os.path.exists(db_path):
            try: 
                os.remove(db_path)
                print(f"Physically Wiped DB: {db_path}")
            except Exception as e:
                print(f"Failed to remove {db_path}: {e}")

    _ensure_directories()
    print("Initializing fresh Ruflo memory...")
    init_code, init_out, init_err = _run_memory_command(["init"])
    if init_code != 0:
        print(f"Memory init warning: {init_err or init_out}")

    _run_memory_command(["delete", "--namespace", NAMESPACE], input_text="Yes\n")
    print("Cleanup phase finished.")

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