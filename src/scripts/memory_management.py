import subprocess
import json
from typing import Optional


# this is gonna be a wrapper function for interacting with mcp server, i saw a lot of projects have something like this
def _run_memory_command(args: list[str]) -> tuple[bool, str]:
    pass

def store_memory(key: str, value: str, namespace: str) -> bool:
    pass

def retrieve_memory(key: str, namespace: str) -> Optional[str]:
    pass

def validate_memory_key(key: str, namespace: str) -> bool:
    pass

def delete_memory(key: str, namespace: str) -> bool:
    pass

# maybe a function like this isnt needed, just saw a lot of projects with it
def list_memory_keys(namespace: str) -> list[str]:
   pass

def clear_workflow_memory():
    pass