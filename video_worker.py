"""First-stage worker: collect video metadata and captions, then submit a draft.

This worker deliberately does not download video, transcribe audio, call an LLM,
or write to Mealie. It is safe to run on any worker host with yt-dlp installed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _vtt_text(value: str, max_chars: int = 30_000) -> str:
    """Turn WebVTT into bounded plain text while removing duplicate cues."""
    lines: list[str] = []
    previous = ""
    for raw in value.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or line.startswith(("NOTE", "STYLE", "REGION")):
            continue
        if "-->" in line or re.fullmatch(r"\d+", line):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line and line != previous:
            lines.append(line)
            previous = line
        if sum(len(item) + 1 for item in lines) >= max_chars:
            break
    return " ".join(lines)[:max_chars]


def extract(source_url: str, runner: Runner = subprocess.run) -> dict[str, Any]:
    """Extract metadata and available subtitles using yt-dlp."""
    with tempfile.TemporaryDirectory(prefix="recipe-worker-") as directory:
        command = [
            "yt-dlp",
            "--no-playlist",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "all",
            "--sub-format",
            "vtt",
            "--dump-single-json",
            "--no-warnings",
            "--output",
            str(Path(directory) / "source.%(ext)s"),
            source_url,
        ]
        completed = runner(command, capture_output=True, text=True, check=False, timeout=300)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "yt-dlp failed").strip()
            raise RuntimeError(detail[-4000:])
        try:
            metadata = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("yt-dlp returned invalid metadata JSON") from exc

        subtitles: list[dict[str, str]] = []
        for subtitle_file in sorted(Path(directory).glob("*.vtt")):
            text = _vtt_text(subtitle_file.read_text(encoding="utf-8", errors="replace"))
            if text:
                subtitles.append({"language": subtitle_file.stem.rsplit(".", 1)[-1], "text": text})

    description = (metadata.get("description") or "").strip()
    warnings: list[str] = []
    if not subtitles:
        warnings.append("No captions were available; audio transcription is not implemented yet.")
    if not description:
        warnings.append("The source has no description; ingredients may only be present in speech or video frames.")
    return {
        "title": metadata.get("title"),
        "uploader": metadata.get("uploader"),
        "duration_seconds": metadata.get("duration"),
        "webpage_url": metadata.get("webpage_url") or source_url,
        "thumbnail": metadata.get("thumbnail"),
        "description": description[:30_000],
        "captions": subtitles,
        "warnings": warnings,
        "stage": "metadata-and-captions",
    }


def api_json(base_url: str, token: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(base_url.rstrip("/") + path, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"queue API {exc.code}: {detail[:1000]}") from exc


def process_one(base_url: str, token: str, worker_id: str, runner: Runner = subprocess.run) -> dict[str, Any] | None:
    claimed = api_json(base_url, token, "/jobs/claim", {"worker_id": worker_id})
    job = claimed.get("job")
    if not job:
        return None
    job_id = job["id"]
    try:
        draft = extract(job["source_url"], runner)
        return api_json(base_url, token, f"/jobs/{job_id}/result", {
            "worker_id": worker_id,
            "draft": draft,
            "warnings": draft["warnings"],
        })
    except Exception as exc:
        return api_json(base_url, token, f"/jobs/{job_id}/fail", {
            "worker_id": worker_id,
            "error": str(exc),
        })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default=os.environ.get("QUEUE_URL", "http://127.0.0.1:8088"))
    parser.add_argument("--token", default=os.environ.get("QUEUE_TOKEN", ""))
    parser.add_argument("--worker-id", default=os.environ.get("WORKER_ID", os.uname().nodename))
    args = parser.parse_args()
    result = process_one(args.queue, args.token, args.worker_id)
    print(json.dumps(result, ensure_ascii=False, indent=2) if result else "No pending jobs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
