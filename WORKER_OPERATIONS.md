# Price Mixer durable worker

Production uses a separate systemd process:

```text
price-mixer.service          Flask/Gunicorn HTTP
price-mixer-worker.service   durable background jobs
```

The SQLite queue is stored at `PRICE_MIXER_JOB_DB`. It supports atomic claim,
bounded retries, lease recovery after worker crashes, job correlation IDs,
coalescing and safe status polling.

The external worker currently executes:

- coalesced generation of `consolidated_price.xlsx`;
- API-source downloads, with progress shared through persistent cache state.

Bulk validate/clean and verify-all-ID already run in isolated subprocesses
with durable status files. Small mutation operations remain serialized in the
single Gunicorn worker, which is why `PRICE_MIXER_WORKERS=1` is still required.

## Operations

```bash
sudo systemctl enable --now price-mixer-worker
sudo systemctl status price-mixer-worker
journalctl -u price-mixer-worker -f
```

Authenticated HTTP status:

```text
GET /api/worker-status
```

Healthy external mode returns `mode=external`, `status=ok`, queue counts and
at least one active worker heartbeat. Worker identifiers and job payloads are
not exposed.

Successful and cancelled queue history older than seven days is removed in
bounded batches. Failed jobs are retained for investigation. Queue data is
operational runtime and is excluded from user-state backups.
