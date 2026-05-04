import os, time
from openai import OpenAI

keys_str = os.getenv("GEMINI_API_KEY", "")
keys = [k.strip().strip('"').strip("'") for k in keys_str.split(",") if k.strip().strip('"').strip("'")]

print(f"Total keys found: {len(keys)}")

base_url = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")

working = 0
for i, key in enumerate(keys[:3]):  # test first 3 keys
    print(f"\nKey {i+1}: {key[:20]}...")
    client = OpenAI(api_key=key, base_url=base_url)
    start = time.time()
    try:
        r = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=10
        )
        latency = round((time.time() - start) * 1000)
        content = r.choices[0].message.content
        print(f"  SUCCESS | Response: {content} | Latency: {latency}ms")
        working += 1
    except Exception as e:
        print(f"  FAILED: {str(e)[:200]}")

print(f"\nResult: {working}/3 keys working")
