"""Smoke-test Cloudflare Workers AI via the scraper's OpenAI-compatible config.

Run from scraper/ after setting:
  CLOUDFLARE_ACCOUNT_ID
  CLOUDFLARE_API_TOKEN
  CLOUDFLARE_WORKERS_AI_MODEL
  CLOUDFLARE_WORKERS_AI_MODEL_ALLOWLIST
"""
from __future__ import annotations

import json
import sys

from openai import OpenAI

from config import (
    INFERENCE_API_KEY,
    INFERENCE_BASE_URL,
    INFERENCE_MODEL,
    INFERENCE_MODEL_ALLOWLIST,
    INFERENCE_PROVIDER,
)
from normalizer import parse_json_response


def main() -> int:
    if INFERENCE_PROVIDER != "cloudflare_workers_ai":
        print(f"Provider is {INFERENCE_PROVIDER!r}, not 'cloudflare_workers_ai'.")
        print("Set CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN, CLOUDFLARE_WORKERS_AI_MODEL,")
        print("and CLOUDFLARE_WORKERS_AI_MODEL_ALLOWLIST in scraper/.env, then rerun.")
        return 2

    if INFERENCE_MODEL not in INFERENCE_MODEL_ALLOWLIST:
        print(f"Model {INFERENCE_MODEL!r} is not allowlisted.")
        return 2

    client = OpenAI(base_url=INFERENCE_BASE_URL, api_key=INFERENCE_API_KEY)
    print(f"Provider: {INFERENCE_PROVIDER}")
    print(f"Model:    {INFERENCE_MODEL}")
    print(f"Base URL: {INFERENCE_BASE_URL}")
    print("Calling Cloudflare Workers AI...")

    resp = client.chat.completions.create(
        model=INFERENCE_MODEL,
        messages=[
            {
                "role": "system",
                "content": "Return only valid compact JSON. No markdown, no prose.",
            },
            {
                "role": "user",
                "content": (
                    "Return JSON with keys ok=true, role_domain='Data & Analytics', "
                    "skills=['Python','SQL']."
                ),
            },
        ],
        temperature=0.0,
        max_tokens=160,
    )
    raw = resp.choices[0].message.content or ""
    parsed = parse_json_response(raw)
    print("Raw response:")
    print(raw)
    print(f"Finish reason: {resp.choices[0].finish_reason}")
    usage = getattr(resp, "usage", None)
    if usage:
        print(f"Tokens — prompt: {usage.prompt_tokens}  completion: {usage.completion_tokens}")
    if not isinstance(parsed, dict) or not parsed.get("ok"):
        print("Cloudflare call completed, but JSON parse/shape check failed.")
        return 1
    print("Cloudflare Workers AI smoke test passed.")
    print(json.dumps(parsed, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
