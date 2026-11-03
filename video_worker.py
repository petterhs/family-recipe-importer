"""Video evidence worker: collect metadata, captions, transcription and OCR.

Transcription and OCR are best-effort and return explicit warnings when their
external tools or models are unavailable. The worker never calls an LLM or
writes to Mealie.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
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


def _run_checked(command: list[str], runner: Runner) -> subprocess.CompletedProcess[str]:
    completed = runner(command, capture_output=True, text=True, check=False, timeout=900)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "command failed").strip()
        raise RuntimeError(f"{command[0]} failed: {detail[-2000:]}")
    return completed


def _transcribe(source_url: str, directory: str, runner: Runner) -> dict[str, str]:
    if not shutil.which("whisper"):
        raise RuntimeError("whisper command is not installed on this worker")
    audio_template = str(Path(directory) / "audio.%(ext)s")
    _run_checked([
        "yt-dlp", "--no-playlist", "--extract-audio", "--audio-format", "wav",
        "--audio-quality", "5", "--no-warnings", "--output", audio_template, source_url,
    ], runner)
    audio_files = sorted(Path(directory).glob("audio.*"))
    if not audio_files:
        raise RuntimeError("yt-dlp did not produce an audio file")
    output_dir = Path(directory) / "transcription"
    output_dir.mkdir()
    _run_checked([
        "whisper", str(audio_files[0]), "--model", os.environ.get("WHISPER_MODEL", "base"),
        "--output_format", "txt", "--output_dir", str(output_dir),
    ], runner)
    text_files = sorted(output_dir.glob("*.txt"))
    if not text_files:
        raise RuntimeError("whisper did not produce a text transcript")
    text = text_files[0].read_text(encoding="utf-8", errors="replace").strip()
    return {"engine": "whisper", "model": os.environ.get("WHISPER_MODEL", "base"), "text": text[:30_000]}


def _ocr(source_url: str, directory: str, runner: Runner) -> list[dict[str, str]]:
    if not shutil.which("ffmpeg") or not shutil.which("tesseract"):
        raise RuntimeError("ffmpeg and tesseract are required for OCR")
    video_template = str(Path(directory) / "video.%(ext)s")
    _run_checked([
        "yt-dlp", "--no-playlist", "-f", "worst[ext=mp4]/worst", "--no-warnings",
        "--output", video_template, source_url,
    ], runner)
    videos = sorted(Path(directory).glob("video.*"))
    if not videos:
        raise RuntimeError("yt-dlp did not produce a video file")
    frames = Path(directory) / "frames"
    frames.mkdir()
    _run_checked([
        "ffmpeg", "-nostdin", "-y", "-i", str(videos[0]), "-vf",
        "fps=1/2,scale=1920:-2,eq=contrast=1.3:brightness=0.05,format=gray",
        str(frames / "frame-%04d.png"),
    ], runner)
    results: list[dict[str, str]] = []
    for frame in sorted(frames.glob("*.png"))[:120]:
        completed = _run_checked(["tesseract", str(frame), "stdout", "--psm", "11"], runner)
        text = (completed.stdout or "").strip()
        if text:
            results.append({"frame": frame.name, "text": text[:4000]})
    return results


def extract(
    source_url: str,
    runner: Runner = subprocess.run,
    *,
    transcribe: bool = True,
    ocr: bool = True,
) -> dict[str, Any]:
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

        transcription: dict[str, str] | None = None
        ocr_results: list[dict[str, str]] = []
        warnings: list[str] = []
        if not subtitles and transcribe:
            try:
                transcription = _transcribe(source_url, directory, runner)
            except Exception as exc:
                warnings.append(f"Audio transcription unavailable: {exc}")
        if ocr:
            try:
                ocr_results = _ocr(source_url, directory, runner)
            except Exception as exc:
                warnings.append(f"Frame OCR unavailable: {exc}")

    description = (metadata.get("description") or "").strip()
    if not subtitles and transcription is None and transcribe:
        warnings.append("No captions or audio transcription were available.")
    if not description:
        warnings.append("The source has no description; recipe details may only be present in speech or video frames.")
    return {
        "title": metadata.get("title"),
        "uploader": metadata.get("uploader"),
        "duration_seconds": metadata.get("duration"),
        "webpage_url": metadata.get("webpage_url") or source_url,
        "thumbnail": metadata.get("thumbnail"),
        "description": description[:30_000],
        "captions": subtitles,
        "transcription": transcription,
        "ocr": ocr_results,
        "warnings": warnings,
        "stage": "metadata-captions-transcription-ocr",
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


def process_one(
    base_url: str,
    token: str,
    worker_id: str,
    runner: Runner = subprocess.run,
    *,
    transcribe: bool = True,
    ocr: bool = True,
) -> dict[str, Any] | None:
    claimed = api_json(base_url, token, "/jobs/claim", {"worker_id": worker_id})
    job = claimed.get("job")
    if not job:
        return None
    job_id = job["id"]
    try:
        draft = extract(job["source_url"], runner, transcribe=transcribe, ocr=ocr)
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


def run_loop(
    base_url: str,
    token: str,
    worker_id: str,
    *,
    once: bool = False,
    max_jobs: int | None = None,
    poll_interval: int = 60,
    transcribe: bool = True,
    ocr: bool = True,
    runner: Runner = subprocess.run,
) -> int:
    """Process jobs until stopped, or until the optional maximum is reached."""
    processed = 0
    while max_jobs is None or processed < max_jobs:
        try:
            result = process_one(
                base_url=base_url,
                token=token,
                worker_id=worker_id,
                runner=runner,
                transcribe=transcribe,
                ocr=ocr,
            )
        except Exception as exc:
            print(f"worker cycle failed: {exc}", flush=True)
            result = None
        if result is not None:
            processed += 1
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if once:
                break
            continue
        if once:
            break
        time.sleep(max(1, poll_interval))
    return processed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default=os.environ.get("QUEUE_URL", "http://127.0.0.1:8088"))
    parser.add_argument("--token", default=os.environ.get("QUEUE_TOKEN", ""))
    parser.add_argument("--worker-id", default=os.environ.get("WORKER_ID", os.uname().nodename))
    parser.add_argument("--once", action="store_true", help="process at most one job and exit")
    parser.add_argument("--max-jobs", type=int, help="stop after processing this many jobs")
    parser.add_argument("--poll-interval", type=int, default=60, help="seconds to wait when no job is available")
    parser.add_argument("--no-transcription", action="store_true", help="skip audio transcription")
    parser.add_argument("--no-ocr", action="store_true", help="skip sampled-frame OCR")
    args = parser.parse_args()
    processed = run_loop(
        args.queue,
        args.token,
        args.worker_id,
        once=args.once,
        max_jobs=args.max_jobs,
        poll_interval=args.poll_interval,
        transcribe=not args.no_transcription,
        ocr=not args.no_ocr,
    )
    if processed == 0:
        print("No pending jobs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
