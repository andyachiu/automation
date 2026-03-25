#!/usr/bin/env python3
"""Quick check that your Anthropic API key is valid and has credits."""

import anthropic
import os
import sys

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    print("❌ ANTHROPIC_API_KEY is not set")
    sys.exit(1)

print(f"Key: {api_key[:8]}...{api_key[-4:]}")

client = anthropic.Anthropic(api_key=api_key)

try:
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1,
        messages=[{"role": "user", "content": "hi"}],
    )
    print("✅ API key works and has credits")
except anthropic.AuthenticationError as e:
    print(f"❌ Invalid API key: {e}")
    sys.exit(1)
except anthropic.BadRequestError as e:
    if "credit" in str(e).lower():
        print(f"❌ Key is valid but no credits: {e}")
    else:
        print(f"❌ Bad request: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
