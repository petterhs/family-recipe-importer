"""Small, verified Mealie adapter for approved recipe imports.

Mealie's POST /api/recipes creates a template and ignores most of the body.
The adapter therefore creates to obtain a slug, PUTs the complete payload, then
GETs the recipe back before returning it. No queue or LLM credentials belong in
this module's payloads.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen


JsonOpener = Callable[..., Any]


def _duration(minutes: Any) -> str | None:
    if minutes is None:
        return None
    try:
        return f"PT{int(minutes)}M"
    except (TypeError, ValueError):
        return None


def build_payload(draft: dict[str, Any]) -> dict[str, Any]:
    ingredients = []
    for item in draft.get("ingredients", []):
        quantity = item.get("quantity")
        unit = item.get("unit")
        name = item.get("name", "").strip()
        display = " ".join(str(value) for value in (quantity, unit, name) if value not in (None, ""))
        ingredients.append({
            "quantity": str(quantity) if quantity is not None else None,
            "unit": unit,
            "food": name,
            "note": "optional" if item.get("optional") else None,
            "display": display,
        })
    payload = {
        "name": draft.get("title", "").strip(),
        "description": draft.get("summary", "").strip(),
        "recipeYield": str(draft["servings"]) if draft.get("servings") is not None else None,
        "prepTime": _duration(draft.get("prep_time_minutes")),
        "cookTime": _duration(draft.get("cook_time_minutes")),
        "totalTime": _duration(draft.get("total_time_minutes")),
        "recipeIngredient": ingredients,
        "recipeInstructions": [
            {"text": text, "position": index + 1}
            for index, text in enumerate(draft.get("instructions", []))
        ],
        "tags": [],
        "recipeCategory": [],
    }
    return {key: value for key, value in payload.items() if value is not None}


class MealieClient:
    def __init__(self, base_url: str, token: str, opener: JsonOpener = urlopen) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.opener = opener

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        request = Request(
            self.base_url + path,
            data=data,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with self.opener(request, timeout=60) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"Mealie {method} {path} failed with HTTP {exc.code}: {detail[:1000]}") from exc

    def import_recipe(self, draft: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        created = self._request("POST", "/api/recipes", {"name": draft["title"]})
        slug = created.get("slug") or (created.get("recipe") or {}).get("slug")
        if not slug:
            raise RuntimeError("Mealie create response did not contain a recipe slug")
        self._request("PUT", f"/api/recipes/{slug}", build_payload(draft))
        verified = self._request("GET", f"/api/recipes/{slug}")
        return slug, verified


def import_from_environment(draft: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    base_url = os.environ.get("MEALIE_URL")
    token = os.environ.get("MEALIE_API_TOKEN")
    if not base_url or not token:
        raise RuntimeError("MEALIE_URL and MEALIE_API_TOKEN are required")
    return MealieClient(base_url, token).import_recipe(draft)
