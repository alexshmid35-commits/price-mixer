# Local cutover and rollback

The migration copy was accepted and switched to the primary local ports on
2026-07-24. The legacy source/runtime remain unchanged and stopped.

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

Stopping the candidate does not touch the legacy source directory or runtime.
Before rollback after any new user changes, create a verified backup of the
current candidate runtime so new ID decisions cannot be lost. Then start the
original legacy launcher only as an emergency fallback.

## Primary local launcher

After acceptance, the candidate runtime can own the normal ports:

```bash
scripts/start_primary_local.sh /absolute/runtime /absolute/onliner-parser
```

This starts the mixer on 5001, its external worker, and the parser on 5055.
`scripts/stop_primary_local.sh /absolute/runtime` stops only these managed
components. The legacy source/runtime and its original launcher remain
unchanged for rollback.
