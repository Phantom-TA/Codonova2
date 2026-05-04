import os, time
from openai import OpenAI

keys_str = os.getenv("GEMINI_API_KEY", "")
keys = [k.strip().strip('"').strip("'") for k in keys_str.split(",") if k.strip().strip('"').strip("'")]
base_url = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")

print(f"Testing all {len(keys)} Gemini API keys...\n")
print("-" * 60)

working = []
exhausted = []
error = []

for i, key in enumerate(keys):
    client = OpenAI(api_key=key, base_url=base_url)
    start = time.time()
    try:
        r = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=5
        )
        latency = round((time.time() - start) * 1000)
        print(f"Key {i+1} [{key[:16]}...] -> WORKING  ({latency}ms)")
        working.append(i+1)
    except Exception as e:
        err_str = str(e)
        latency = round((time.time() - start) * 1000)
        if "429" in err_str or "quota" in err_str.lower() or "exceeded" in err_str.lower():
            print(f"Key {i+1} [{key[:16]}...] -> EXHAUSTED (quota exceeded)")
            exhausted.append(i+1)
        elif "503" in err_str or "overload" in err_str.lower() or "unavailable" in err_str.lower():
            print(f"Key {i+1} [{key[:16]}...] -> SERVER DOWN (503 - retry later)")
            error.append(i+1)
        else:
            print(f"Key {i+1} [{key[:16]}...] -> ERROR: {err_str[:120]}")
            error.append(i+1)
    time.sleep(0.5)  # avoid hitting rate limits during the test itself

print("-" * 60)
print(f"\nSUMMARY:")
print(f"  Working:   {len(working)} keys -> {working}")
print(f"  Exhausted: {len(exhausted)} keys -> {exhausted}")
print(f"  Errors:    {len(error)} keys -> {error}")
print(f"\n  Effective remaining capacity: ~{len(working) * 500} requests today")
