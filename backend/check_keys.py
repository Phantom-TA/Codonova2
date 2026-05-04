import os, sys
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

keys_str = os.getenv("GEMINI_API_KEY", "")
keys = [k.strip().strip('"').strip("'") for k in keys_str.split(",") if k.strip().strip('"').strip("'")]
model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
base_url = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")

print(f"Testing {len(keys)} Gemini API keys against model: {model}\n")
print(f"{'#':<4} {'Key (last 6)':<14} {'Status':<20} {'Tokens'}")
print("-" * 60)

ok_count = 0
for i, key in enumerate(keys, 1):
    client = OpenAI(api_key=key, base_url=base_url, max_retries=0)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=5,
            temperature=0,
        )
        tokens = getattr(resp.usage, "total_tokens", "?")
        print(f"{i:<4} ...{key[-6:]:<14} {'✅ WORKING':<20} {tokens} tokens")
        ok_count += 1
    except Exception as e:
        err = str(e)
        if "429" in err or "quota" in err.lower() or "exhausted" in err.lower() or "resource_exhausted" in err.lower():
            status = "❌ QUOTA EXHAUSTED"
        elif "403" in err or "invalid" in err.lower() or "permission" in err.lower():
            status = "❌ INVALID/DENIED"
        elif "400" in err:
            status = "⚠️  BAD REQUEST"
        else:
            status = f"⚠️  ERROR"
        print(f"{i:<4} ...{key[-6:]:<14} {status:<20} {err[:60]}")

print("-" * 60)
print(f"\nResult: {ok_count}/{len(keys)} keys working")
