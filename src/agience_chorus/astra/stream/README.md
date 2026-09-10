# Stream Server (SRS)

This directory contains the SRS RTMP/HLS ingest server for Agience live streaming.

## What's here

### Stream Server (`stream/`)
- Based on SRS 5 (`ossrs/srs:5`)
- RTMP ingest on container port `1936`
- HLS output served via SRS HTTP server on container port `1985`
- Automatically calls Astra on publish/unpublish via HTTP hooks:
	- `POST /stream/publish`
	- `POST /stream/unpublish`

See `Dockerfile` and `entrypoint.sh`.

## Architecture

```
OBS -> RTMP -> SRS (1936) -> HLS output (/var/stream/)
                   |
           on_publish/on_unpublish webhooks
                   |
                   v
         Astra stream_routes.py
           -> creates session artifact (via Core API)
           -> on unpublish: ffmpeg HLS->MP4, upload to S3
```

Lumen carries no transcription tool — its answer path is grounded operators — so there is no
transcription step. AWS credentials are stored as Seraph Secrets (not env vars).
