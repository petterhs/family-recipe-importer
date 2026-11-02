# Family Recipe Importer

Queued video-recipe importer for a self-hosted Mealie installation.

> This repository is private while the architecture and worker protocol are developed. It may be open-sourced later.

## Planned architecture

- **Queue API:** runs on a stable always-on node and stores pending jobs and recipe drafts.
- **Workers:** poll the queue from available machines such as `fatman` or `no-kon-lx-016`.
- **Video extraction:** use `yt-dlp`, captions first, then transcription/OCR where needed.
- **Review:** workers produce a draft; a human approves ingredients before anything is written to Mealie.
- **Mealie:** the queue service or approved client writes the final recipe and reads it back for verification.

The queue must tolerate workers going offline, use leases for claimed jobs, and never store API keys in the repository or job payloads.

## Status

Repository scaffold only. No deployment or Mealie write integration is included yet.

## License

MIT. See [LICENSE](LICENSE).
