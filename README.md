# Family Recipe Importer

Queued video-recipe importer for a self-hosted Mealie installation.

> This repository is private while the architecture and worker protocol are developed. It may be open-sourced later.

## Planned architecture

- **Queue API:** runs on a stable always-on node and stores pending jobs and recipe drafts.
- **Workers:** poll the queue from available machines such as `fatman` or `no-kon-lx-016`.
- **Video extraction:** use `yt-dlp`, captions first, then transcription/OCR where needed.
- **Current worker:** `video_worker.py` claims one job, collects metadata/description/thumbnail and available VTT captions, and submits a `review` draft. It does not download media, transcribe audio, call an LLM, or write to Mealie.
- **Review:** workers produce a draft; a human approves ingredients before anything is written to Mealie.
- **Mealie:** the queue service or approved client writes the final recipe and reads it back for verification.

The queue must tolerate workers going offline, use leases for claimed jobs, and never store API keys in the repository or job payloads.

## Status

The first queue API prototype is implemented. It stores jobs in SQLite, supports worker leases, accepts recipe drafts, and requires a bearer token when `QUEUE_TOKEN` is configured. Video download, transcription, OCR, Mealie integration, and Hermes/Signal integration are intentionally not included yet.

## Local test

```bash
python -m unittest -v
```

Run the API locally:

```bash
python queue_api.py
```

Create a job:

```bash
curl -H "Authorization: Bearer $QUEUE_TOKEN" \\
  -H 'Content-Type: application/json' \\
  -d '{"source_url":"https://www.youtube.com/shorts/example"}' \\
  http://127.0.0.1:8088/jobs
```

## License

MIT. See [LICENSE](LICENSE).
