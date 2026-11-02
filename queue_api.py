from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, request

from recipe_queue import Queue, STATUSES


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__)
    queue = Queue(db_path or os.environ.get("QUEUE_DB", "queue.db"))
    token = os.environ.get("QUEUE_TOKEN")

    def authorized() -> bool:
        return not token or request.headers.get("Authorization") == f"Bearer {token}"

    @app.before_request
    def require_auth():
        if not authorized():
            return jsonify(error="unauthorized"), 401
        return None

    @app.post("/jobs")
    def create_job():
        body = request.get_json(silent=True) or {}
        try:
            job = queue.create(body["source_url"], body.get("source_type", "video"), body.get("payload"))
        except (KeyError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(job), 201

    @app.get("/jobs")
    def list_jobs():
        status = request.args.get("status")
        try:
            return jsonify(jobs=queue.list(status, int(request.args.get("limit", 50))))
        except (ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400

    @app.get("/jobs/<job_id>")
    def get_job(job_id: str):
        job = queue.get(job_id)
        return (jsonify(job), 200) if job else (jsonify(error="not found"), 404)

    @app.post("/jobs/claim")
    def claim_job():
        body = request.get_json(silent=True) or {}
        worker_id = body.get("worker_id")
        if not worker_id:
            return jsonify(error="worker_id is required"), 400
        return jsonify(job=queue.claim(worker_id))

    @app.post("/jobs/<job_id>/result")
    def result(job_id: str):
        body = request.get_json(silent=True) or {}
        try:
            job = queue.result(job_id, body["worker_id"], body["draft"], body.get("warnings", []))
        except (KeyError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(job)

    @app.post("/jobs/<job_id>/fail")
    def fail(job_id: str):
        body = request.get_json(silent=True) or {}
        try:
            job = queue.fail(job_id, body["worker_id"], body["error"])
        except (KeyError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(job)

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8088")))
