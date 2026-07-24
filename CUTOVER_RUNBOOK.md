# Local parallel cutover

The migration copy runs independently from the working mixer. The legacy
instance remains on port 5001 and the candidate instance uses port 5012.

## Start candidate

```bash
PRICE_MIXER_PYTHON=/absolute/path/to/python \
scripts/start_parallel_local.sh /absolute/path/to/runtime 5012
```

The script starts one web process and one external durable worker. When GNU
Screen is available it uses detached named sessions; elsewhere it uses PID
files. Process metadata and logs live inside the selected runtime, not in the
source tree.

## Acceptance

1. Confirm `/api/health`, `/api/version`, and `/api/worker-status`.
2. Open an existing real session and compare dashboard counters.
3. Run N-Tech and IVEN PC checks on a small selection.
4. Confirm and clear a test ID for each supplier, then reload the page.
5. Download XLSX and verify the same lowest-price/duplicate-ID policy.
6. Export to a disposable Google Sheets tab and confirm its sheet ID is
   preserved.

Do not run mutating actions in the legacy and candidate instances at the same
time. Their runtime copies are independent, so a decision made after the copy
exists only in the instance where it was made.

## Stop or roll back

```bash
scripts/stop_parallel_local.sh /absolute/path/to/runtime
```

Stopping the candidate does not touch the legacy process, source directory, or
runtime. Rollback is therefore immediate: continue using port 5001. Keep the
verified baseline backup until final acceptance and a fresh post-cutover
backup are complete.
