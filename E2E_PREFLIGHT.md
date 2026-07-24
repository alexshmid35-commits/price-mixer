# E2E and production preflight

## Isolated end-to-end check

Run:

```bash
npm run test:e2e
```

The suite starts the web application and durable worker on
`127.0.0.1:5011`. All mutable state is created under
`test-results/e2e-runtime`; the normal application state, uploads, cache,
databases, credentials, and the service on port 5001 are not used.

The check covers health/version/request correlation, authentication, worker
heartbeat, the upload form, a synthetic CSV upload, consolidation statistics,
and XLSX download.

Server and worker logs are written to `test-results/e2e-server.log` and
`test-results/e2e-worker.log`.

## Production checks

Before starting services:

```bash
.venv/bin/python deploy/check_production.py
```

After starting the worker and web service:

```bash
.venv/bin/python deploy/smoke_production.py
```

The smoke command reads credentials from the environment, sends them only to
the loopback service, and never prints their values or response bodies.
It requires a healthy external worker by default. For local development only,
set `PRICE_MIXER_SMOKE_REQUIRE_WORKER=0` to accept inline background mode.
