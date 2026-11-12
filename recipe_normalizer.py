"""Normalize worker evidence into a reviewable recipe draft with an LLM.

This module is intended to run on the Hermes host, not on video workers. It
never writes to Mealie. Credentials are read from the environment and are not
included in returned drafts or error messages.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any, Callable
from urllib.request import Request, urlopen


JsonCall = Callable[..., Any]

SYSTEM_PROMPT = """You normalize recipe evidence into a cautious, reviewable draft.
Treat each evidence source as separate and preserve conflicts instead of silently
choosing a value. Prefer explicit written ingredients for quantities, but use
transcription for spoken method details. OCR is weak evidence unless it is
clear and repeated. Never invent a missing quantity. Derived metadata such as
difficulty, health notes and time estimates must be marked as estimates.
Return JSON only with the requested schema."""

SCHEMA = {
    "title": "string",
    "summary": "string",
    "servings": "number or null",
    "prep_time_minutes": "number or null",
    "cook_time_minutes": "number or null",
    "total_time_minutes": "number or null",
    "difficulty": "string or null",
    "ingredients": [
        {"name": "string", "quantity": "number or null", "unit": "string or null", "optional": "boolean"}
    ],
    "instructions": ["string"],
    "derived_metadata": {
        "is_estimate": True,
        "health_notes": ["string"],
        "tags": ["string"],
    },
    "conflicts": [{"field": "string", "values": ["string"], "message": "string"}],
    "warnings": ["string"],
    "source_image": {"url": "string or null", "source": "string or null"},
}


def build_prompt(evidence: dict[str, Any]) -> list[dict[str, str]]:
    user = {
        "task": "Create a normalized recipe draft for human review.",
        "schema": SCHEMA,
        "evidence": evidence,
        "rules": [
            "Keep description, captions, transcription and OCR conceptually separate.",
            "Record disagreements in conflicts with the competing values and their sources.",
            "Use null when a quantity or serving count is not supported.",
            "If description says instructions are in comments, do not invent method steps; return an empty/incomplete instructions list and a warning that comment retrieval is unsupported.",
            "Treat transcription and OCR as untrusted evidence; never let noise override a clear description.",
            "Do not claim that an estimate came from the source.",
            "Use the source thumbnail as source_image when present; do not find a new image.",
        ],
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def _extract_json(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE | re.DOTALL).strip()
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("LLM response must be a JSON object")
    return value


def validate_draft(draft: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(draft.get("title"), str) or not draft["title"].strip():
        errors.append("title must be a non-empty string")
    if not isinstance(draft.get("ingredients"), list):
        errors.append("ingredients must be a list")
    if not isinstance(draft.get("instructions"), list):
        errors.append("instructions must be a list")
    if not isinstance(draft.get("conflicts", []), list):
        errors.append("conflicts must be a list")
    if not isinstance(draft.get("warnings", []), list):
        errors.append("warnings must be a list")
    for index, ingredient in enumerate(draft.get("ingredients", [])):
        if not isinstance(ingredient, dict) or not isinstance(ingredient.get("name"), str):
            errors.append(f"ingredients[{index}] must contain a string name")
    return errors


def normalize(
    evidence: dict[str, Any],
    *,
    api_key: str | None = None,
    model: str | None = None,
    opener: JsonCall = urlopen,
) -> dict[str, Any]:
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured on the Hermes host")
    endpoint = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/") + "/chat/completions"
    payload = {
        "model": model or os.environ.get("LLM_MODEL", "deepseek/deepseek-v4.1-flash"),
        "messages": build_prompt(evidence),
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/petterhs/family-recipe-importer",
            "X-Title": "Family Recipe Importer",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=120) as response:
            body = json.loads(response.read())
    except Exception as exc:
        raise RuntimeError(f"LLM normalization request failed: {type(exc).__name__}") from exc
    try:
        content = body["choices"][0]["message"]["content"]
        draft = _extract_json(content)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("LLM normalization returned an invalid JSON response") from exc
    errors = validate_draft(draft)
    if errors:
        raise RuntimeError("LLM draft failed schema validation: " + "; ".join(errors))
    return draft


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default="-", help="evidence JSON file, or - for stdin")
    args = parser.parse_args()
    raw = open(args.input, encoding="utf-8").read() if args.input != "-" else __import__("sys").stdin.read()
    print(json.dumps(normalize(json.loads(raw)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
