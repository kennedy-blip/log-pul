# LogPulse

Structured-log anomaly, error-spike and root-cause correlation dashboard.

## Stack
- Vanilla HTML/CSS/JavaScript in public/; no TypeScript or bundler
- Python 3.12 Vercel Serverless Functions in api/
- Python standard library and in-memory SQLite

## Features
- Seeded checkout database-pool spike, healthy worker, and auth 401 surge
- JSON-lines and timestamp/level/service/endpoint/message parsing
- Dynamic ID, UUID, number and timestamp normalization
- Severity counts, configurable spike threshold, signature clusters
- Top offending endpoints/traces and triage recommendations
- Offline browser fallback analyzer

## Local checks
```bash
python3 -m py_compile api/streams.py api/correlate.py
python3 -m json.tool vercel.json
python3 -m http.server 8000 -d public
```

## API
- GET /api/streams — seeded streams and entries
- POST /api/streams — ingest a batch or reset presets with {"reset":true}
- POST /api/correlate — analyze {streamId, rawLogs, errorSpikeThresholdPct}

## Deploy
Import the repository into Vercel with the repository root as the project root. No Node build step is needed. The Vercel config routes Python functions and serves the public directory.

## Persistence note
SQLite is deliberately in-memory for serverless compatibility and demo data. Function instances are ephemeral, so ingested records do not persist between requests. For durable production retention, use a managed database or log store.
```
