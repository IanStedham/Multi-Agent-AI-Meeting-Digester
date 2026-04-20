import time
import os
import anthropic
from dotenv import load_dotenv
from memory_management import store_memory, retrieve_memory

def test_diagnostics():
    load_dotenv()
    print("--- Starting Partner Diagnostics ---")
    
    # 1. Test Anthropic Connectivity
    print("\n[1/2] Testing Anthropic API (Claude)...")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    start = time.time()
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001", # Use a small model for speed
            max_tokens=10,
            messages=[{"role": "user", "content": "Hi"}]
        )
        print(f"✅ Anthropic responded in {time.time() - start:.2f}s")
    except Exception as e:
        print(f"❌ Anthropic Connection Failed: {e}")

    # 2. Test Ruflo Memory Speed
    print("\n[2/2] Testing Ruflo Memory Speed...")
    start = time.time()
    success = store_memory("diag_test", "test_value")
    if success:
        val = retrieve_memory("diag_test")
        print(f"✅ Memory write/read took {time.time() - start:.2f}s")
    else:
        print("❌ Memory storage is hanging or failing.")

if __name__ == "__main__":
    test_diagnostics()