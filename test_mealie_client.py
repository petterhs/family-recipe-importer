from __future__ import annotations

import json
import unittest

from mealie_client import MealieClient, build_payload


DRAFT = {
    "title": "Tomato pasta",
    "summary": "A quick dinner",
    "servings": 4,
    "prep_time_minutes": 5,
    "cook_time_minutes": 15,
    "total_time_minutes": 20,
    "ingredients": [{"name": "tomatoes", "quantity": 400, "unit": "g", "optional": False}],
    "instructions": ["Cook the tomatoes.", "Serve."],
    "source_image": {"url": "https://images.example/tomato.jpg", "source": "video thumbnail"},
}


class Response:
    def __init__(self, body=None, content=b"", content_type="application/json"):
        self.body = body
        self.content = content
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *args):
        return self.content or json.dumps(self.body).encode()


class MealieClientTests(unittest.TestCase):
    def test_payload_has_explicit_durations_and_structured_ingredients(self):
        payload = build_payload(DRAFT)
        self.assertEqual(payload["prepTime"], "PT5M")
        self.assertEqual(payload["totalTime"], "PT20M")
        self.assertEqual(payload["recipeIngredient"][0]["display"], "400 g tomatoes")
        self.assertEqual(payload["recipeInstructions"][1]["position"], 2)

    def test_create_put_and_read_back(self):
        calls = []

        def opener(request, timeout):
            if request.full_url == "https://images.example/tomato.jpg":
                return Response(content=b"jpeg-bytes", content_type="image/jpeg")
            calls.append((request.method, request.full_url, json.loads(request.data) if request.data and request.headers.get("Content-Type") == "application/json" else request.data))
            if request.method == "PUT" and request.full_url.endswith("/image"):
                return Response(content=b"")
            if request.method == "POST":
                return Response({"slug": "tomato-pasta"})
            if request.method == "PUT":
                return Response({"slug": "tomato-pasta"})
            return Response({"slug": "tomato-pasta", "name": "Tomato pasta", "image": "tomato-pasta.jpg", "recipeIngredient": []})

        slug, verified = MealieClient("https://mealie.example", "token", opener).import_recipe(DRAFT)
        self.assertEqual(slug, "tomato-pasta")
        self.assertEqual(verified["name"], "Tomato pasta")
        self.assertEqual(verified["image"], "tomato-pasta.jpg")
        self.assertEqual([call[0] for call in calls], ["POST", "PUT", "PUT", "GET"])
        self.assertEqual(calls[1][1], "https://mealie.example/api/recipes/tomato-pasta")
        self.assertTrue(calls[2][1].endswith("/api/recipes/tomato-pasta/image"))


if __name__ == "__main__":
    unittest.main()
