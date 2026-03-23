import sys
import os
import json

from memory_management import (
    store_memory,
    retrieve_memory,
    validate_memory_key,
    delete_memory,
    list_memory_keys,
    clear_workflow_memory
)

# ─────────────────────────────────────────────
# Test helpers
# ─────────────────────────────────────────────

PASSED = 0
FAILED = 0
NAMESPACE = "test"

def test(name: str, condition: bool):
    global PASSED, FAILED
    if condition:
        print(f"  [PASS] {name}")
        PASSED += 1
    else:
        print(f"  [FAIL] {name}")
        FAILED += 1


# ─────────────────────────────────────────────
# Individual tests
# ─────────────────────────────────────────────

def test_store_and_retrieve():
    print("\n--- store_memory / retrieve_memory ---")

    # Basic store and retrieve
    store_memory("test:basic", "hello world", NAMESPACE)
    result = retrieve_memory("test:basic", NAMESPACE)
    test("stores and retrieves a plain string", result == "hello world")

    # Store and retrieve JSON string
    data = json.dumps({"name": "Alice", "role": "Engineer"})
    store_memory("test:json", data, NAMESPACE)
    raw = retrieve_memory("test:json", NAMESPACE)

    # Guard against None before parsing so one failure
    # doesn't crash the entire test run
    if raw is not None and raw.strip():
        try:
            parsed = json.loads(raw)
            test("stores and retrieves a JSON string", parsed["name"] == "Alice")
        except json.JSONDecodeError as e:
            print(f"  [DEBUG] JSON parse failed: {e}")
            print(f"  [DEBUG] Raw value was: '{raw}'")
            test("stores and retrieves a JSON string", False)
    else:
        print(f"  [DEBUG] retrieve returned: {repr(raw)}")
        test("stores and retrieves a JSON string", False)

    # Retrieve a key that doesn't exist
    result = retrieve_memory("test:nonexistent", NAMESPACE)
    test("returns None for a missing key", result is None)

    # Store with empty key
    result = store_memory("", "some value", NAMESPACE)
    test("rejects an empty key on store", result is False)

    # Store with None value
    result = store_memory("test:none", None, NAMESPACE)
    test("rejects a None value on store", result is False)


def test_validate():
    print("\n--- validate_memory_key ---")

    # Key that exists
    store_memory("test:validate", "i exist", NAMESPACE)
    test("returns True for a key that exists",
         validate_memory_key("test:validate", NAMESPACE) is True)

    # Key that doesn't exist
    test("returns False for a key that doesn't exist",
         validate_memory_key("test:missing", NAMESPACE) is False)


def test_delete():
    print("\n--- delete_memory ---")

    # Store then delete
    store_memory("test:delete_me", "temporary", NAMESPACE)
    test("key exists before delete",
         validate_memory_key("test:delete_me", NAMESPACE) is True)

    delete_memory("test:delete_me", NAMESPACE)
    test("key is gone after delete",
         validate_memory_key("test:delete_me", NAMESPACE) is False)

    # Delete a key that doesn't exist (should not crash)
    result = delete_memory("test:already_gone", NAMESPACE)
    test("delete on missing key does not crash", True)  # if we got here it didn't crash


def test_list_keys():
    print("\n--- list_memory_keys ---")

    # Store a couple of known keys
    store_memory("test:list_a", "value a", NAMESPACE)
    store_memory("test:list_b", "value b", NAMESPACE)

    keys = list_memory_keys(NAMESPACE)
    test("returns a list", isinstance(keys, list))
    test("list contains stored keys",
         "test:list_a" in keys and "test:list_b" in keys)


def test_clear_workflow_memory():
    print("\n--- clear_workflow_memory ---")

    # Store all the workflow keys
    workflow_keys = [
        ("meeting:transcript",     "some transcript text"),
        ("employees:roster",       json.dumps([{"name": "Bob"}])),
        ("workflow:plan",          "step 1, step 2"),
        ("workflow:status",        "dissecting"),
        ("meeting:raw_tasks",      json.dumps([{"task_id": "T001"}])),
        ("meeting:assigned_tasks", json.dumps([{"task_id": "T001", "assigned_to": "Bob"}])),
        ("emails:drafted",         json.dumps({"individual_emails": []})),
    ]

    for key, value in workflow_keys:
        store_memory(key, value, "workflow")

    # Confirm they're all there
    all_stored = all(
        validate_memory_key(key, "workflow")
        for key, _ in workflow_keys
    )
    test("all workflow keys stored before clear", all_stored)

    # Run the clear
    clear_workflow_memory()

    # Confirm they're all gone
    all_cleared = all(
        not validate_memory_key(key, "workflow")
        for key, _ in workflow_keys
    )
    test("all workflow keys gone after clear", all_cleared)


def test_overwrite():
    print("\n--- overwrite behaviour ---")

    store_memory("test:overwrite", "original", NAMESPACE)
    store_memory("test:overwrite", "updated", NAMESPACE)
    result = retrieve_memory("test:overwrite", NAMESPACE)
    test("storing to an existing key overwrites it", result == "updated")


# ─────────────────────────────────────────────
# Cleanup
# ─────────────────────────────────────────────

def cleanup():
    """Remove all test keys we created during the tests."""
    test_keys = [
        "test:basic",
        "test:json",
        "test:validate",
        "test:list_a",
        "test:list_b",
        "test:overwrite",
    ]
    for key in test_keys:
        delete_memory(key, NAMESPACE)


# ─────────────────────────────────────────────
# Run all tests
# ─────────────────────────────────────────────

def run_all_tests():
    print("\n" + "="*50)
    print("   Memory Management Tests")
    print("="*50)

    test_store_and_retrieve()
    test_validate()
    test_delete()
    test_list_keys()
    test_clear_workflow_memory()
    test_overwrite()

    print("\n--- Cleaning up test keys ---")
    cleanup()
    print("    Done.")

    print("\n" + "="*50)
    print(f"   Results: {PASSED} passed, {FAILED} failed")
    print("="*50 + "\n")

    if FAILED > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()