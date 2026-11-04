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
            calls.append((request.method, request.full_url, json.loads(request.data) if request.data else None))
            if request.method == "POST":
                return Response({"slug": "tomato-pasta"})
            if request.method == "PUT":
                return Response({"slug": "tomato-pasta"})
            return Response({"slug": "tomato-pasta", "name": "Tomato pasta", "recipeIngredient": []})

        slug, verified = MealieClient("https://mealie.example", "token", opener).import_recipe(DRAFT)
        self.assertEqual(slug, "tomato-pasta")
        self.assertEqual(verified["name"], "Tomato pasta")
        self.assertEqual([call[0] for call in calls], ["POST", "PUT", "GET"])
        self.assertEqual(calls[1][1], "https://mealie.example/api/recipes/tomato-pasta")


if __name__ == "__main__":
    unittest.main()
