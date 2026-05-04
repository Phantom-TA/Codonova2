import os, time
from openai import OpenAI

key = os.getenv("OPENROUTER_API_KEY", "")
base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.2-3b-instruct:free")

print(f"OpenRouter Key: {key[:20]}...")
print(f"Model: {model}")
print(f"Base URL: {base_url}")
print("-" * 60)

client = OpenAI(api_key=key, base_url=base_url)
start = time.time()
try:
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Say OK"}],
        max_tokens=10
    )
    latency = round((time.time() - start) * 1000)
    content = r.choices[0].message.content
    print(f"STATUS: WORKING")
    print(f"Response: {content}")
    print(f"Latency: {latency}ms")
    if r.usage:
        print(f"Tokens used: {r.usage.total_tokens}")
except Exception as e:
    latency = round((time.time() - start) * 1000)
    err = str(e)
    if "429" in err or "rate" in err.lower():
        print(f"STATUS: RATE LIMITED (try again in a few minutes)")
    elif "401" in err or "invalid" in err.lower():
        print(f"STATUS: INVALID KEY (check your OpenRouter API key)")
    elif "403" in err:
        print(f"STATUS: FORBIDDEN (key may be suspended)")
    else:
        print(f"STATUS: FAILED")
    print(f"Error: {err[:300]}")
