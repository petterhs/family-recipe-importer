# Family Recipe Importer

Queued video-recipe importer for a self-hosted Mealie installation.

> This repository is private while the architecture and worker protocol are developed. It may be open-sourced later.

## Planned architecture

- **Queue API:** runs on a stable always-on node and stores pending jobs and recipe drafts.
- **Workers:** poll the queue from available machines such as `fatman` or `no-kon-lx-016`.
- **Video extraction:** use `yt-dlp`, captions first, then transcription/OCR where needed.
This worker now attempts audio transcription when captions are absent and sampled-frame OCR by default. Both are best-effort: missing tools or a failed extraction become explicit warnings in the draft instead of silently failing the job. The current Nix wrapper provides `yt-dlp`, `ffmpeg` and `tesseract`; a `whisper` executable and its model are still required for local transcription.
- **Mealie:** the approved client writes the final recipe and reads it back for verification.

The queue must tolerate workers going offline, use leases for claimed jobs, and never store API keys in the repository or job payloads.

## Status

The first queue API prototype is implemented. It stores jobs in SQLite, supports worker leases, prevents duplicate active jobs for the same exact source URL, allows retrying failed jobs, accepts recipe drafts, and requires a bearer token when `QUEUE_TOKEN` is configured. Video download, transcription, OCR, Mealie integration, and Hermes/Signal integration are intentionally not included yet.

`video_worker.py` now supports both one-shot and long-running modes:

```bash
python video_worker.py --once
python video_worker.py --poll-interval 60
python video_worker.py --max-jobs 10 --poll-interval 30
```

## Local test

```bash
python -m unittest -v
```

Run the API locally:

```bash
python queue_api.py
```

The planned deployment location for the queue API is **littleboy**, not Travis. Travis should remain the Hermes/Signal node; littleboy can host the persistent SQLite queue alongside (but separately from) Mealie. Workers on `fatman` or `no-kon-lx-016` will connect to littleboy over the Tailnet.

Create a job:

```bash
curl -H "Authorization: Bearer ***" \\
  -H 'Content-Type: application/json' \\
  -d '{"source_url":"https://www.youtube.com/shorts/example"}' \\
  http://127.0.0.1:8088/jobs
```

A newly created job returns HTTP `201` and `{"job": {...}, "duplicate": false}`. Re-submitting the same exact URL while its job is `pending`, `processing`, `review`, `approved`, or `imported` returns HTTP `200` with the existing job and `"duplicate": true`. Failed jobs are not deduplicated, so they can be retried.

## Backlog

This is the durable project backlog. Update it when a milestone is completed so the implementation does not depend on chat history.

### Queue and worker foundation

- [x] SQLite queue with leases and worker ownership
- [x] Bearer-token API
- [x] Nix flake package and NixOS module
- [x] Queue API deployment configuration for littleboy
- [x] One-shot and polling worker modes
- [x] End-to-end metadata/captions smoke test with a public YouTube Short
- [x] Prevent duplicate active jobs for the same exact source URL
- [ ] Add explicit retry/requeue endpoint and retry limits
- [ ] Add notification bookkeeping for review jobs

### Video evidence extraction

- [x] Download audio only when captions are unavailable or insufficient
- [x] Add default audio transcription attempt on workers (requires a `whisper` executable and model)
- [x] Add sampled-frame OCR by default, with bounded output and warnings
- [x] Store captions, description, transcription and OCR as separate evidence fields
- [ ] Add cleanup/retention policy for temporary media and evidence artifacts

### Hermes and recipe processing

- [ ] Add Hermes-side queue client/tool for enqueue, status and approval
- [ ] Treat a message containing only a video URL as an import request
- [ ] Poll for new `review` jobs without repeatedly notifying the same job
- [ ] Use the LLM to normalize evidence into a structured recipe draft
- [ ] Label derived metadata such as time, difficulty and health notes as estimates
- [ ] Add concise Signal review and `godkjenn <job-id>` flow
- [ ] Write approved recipes to Mealie and read back the exact object for validation
- [ ] Return the verified Mealie recipe link

### Images and sources

- [ ] Prefer a verified source thumbnail when it depicts the dish
- [ ] Fall back to a useful video frame
- [ ] Use external images only with an explicit reuse license
- [ ] Preserve source URLs and image attribution in the draft

### Later

- [ ] Batch URL imports
- [ ] Instagram collection URL extraction helper
- [ ] Optional Mealie staging mode with an explicit opt-in
- [ ] Evaluate a Rust worker only if Python orchestration becomes a measured bottleneck

## License

MIT. See [LICENSE](LICENSE).
