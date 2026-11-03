from __future__ import annotations

import json
import unittest

from recipe_normalizer import _extract_json, build_prompt, normalize, validate_draft


EVIDENCE = {
    "title": "Dinner in 20 minutes",
    "description": "Serves: 4\n600g beef mince\n2 cloves garlic",
    "captions": [],
    "transcription": {"text": "500 grams mince and one large clove of garlic"},
    "ocr": [{"frame": "frame-0001.png", "text": "smoked paprika"}],
    "thumbnail": "https://example.test/thumb.jpg",
}


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.body).encode()


class NormalizerTests(unittest.TestCase):
    def test_prompt_keeps_sources_and_conflict_rules(self):
        messages = build_prompt(EVIDENCE)
        self.assertIn("description", messages[1]["content"])
        self.assertIn("conflicts", messages[1]["content"])

    def test_extract_json_accepts_markdown_fence(self):
        self.assertEqual(_extract_json("```json\n{\"title\": \"Soup\"}\n```"), {"title": "Soup"})

    def test_normalize_parses_and_validates_response(self):
        draft = {
            "title": "Beef curry",
            "summary": "One-pot curry",
            "servings": 4,
            "prep_time_minutes": 5,
            "cook_time_minutes": 15,
            "total_time_minutes": 20,
            "difficulty": "easy",
            "ingredients": [{"name": "beef mince", "quantity": 600, "unit": "g", "optional": False}],
            "instructions": ["Brown the mince."],
            "derived_metadata": {"is_estimate": True, "health_notes": [], "tags": []},
            "conflicts": [{"field": "beef quantity", "values": ["600 g", "500 g"], "message": "Sources disagree."}],
            "warnings": ["Confirm the beef quantity."],
            "source_image": {"url": "https://example.test/thumb.jpg", "source": "video thumbnail"},
        }

        def opener(request, timeout):
            self.assertEqual(request.get_header("Authorization"), "Bearer secret-not-logged")
            return Response({"choices": [{"message": {"content": json.dumps(draft)}}]})

        result = normalize(EVIDENCE, api_key="secret-not-logged", opener=opener)
        self.assertEqual(result["title"], "Beef curry")
        self.assertEqual(result["conflicts"][0]["values"], ["600 g", "500 g"])

    def test_validate_requires_recipe_lists(self):
        errors = validate_draft({"title": "Soup"})
        self.assertIn("ingredients must be a list", errors)
        self.assertIn("instructions must be a list", errors)


if __name__ == "__main__":
    unittest.main()
