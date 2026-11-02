"""
Run this standalone to see the REAL error your LLM call is hitting,
instead of it being silently swallowed by rag_chat.py's except Exception.

Usage: python debug_llm_call.py
(run from your autovm/ root, with .env containing your key)
"""

from dotenv import load_dotenv

load_dotenv()

import os
import openai

api_key = os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY")
print("Key found:", bool(api_key))
print("Key starts with:", api_key[:8] if api_key else None)

base_url = "https://api.groq.com/openai/v1" if os.environ.get("GROQ_API_KEY") else None
print("Using base_url:", base_url)

client = openai.OpenAI(api_key=api_key, base_url=base_url)

try:
    resp = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[{"role": "user", "content": "Say hello in 5 words."}],
        max_tokens=50,
    )

    print("SUCCESS:", resp.choices[0].message.content)
except Exception as e:
    print("REAL ERROR (this is what's being hidden):")
    print(type(e).__name__, "-", e)
