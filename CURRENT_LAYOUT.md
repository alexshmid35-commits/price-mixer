# Current Price Mixer layout

The active release is intentionally split into code and runtime data.

## Code release

`PriceMixer_next_2026-07-24` contains everything required to run the product:

- Price Mixer web application and durable worker;
- embedded `onliner-parser` source;
- local and production launch scripts;
- one dependency set in `requirements-prod.txt`;
- tests and deployment units.

Run `scripts/bootstrap_local.sh` once on a new machine. It creates `.venv` for
the mixer, worker, and parser. A virtualenv is platform-specific and must be
recreated after uploading the source to Linux rather than copied from macOS.

## Runtime data

`PriceMixer_next_runtime_2026-07-24` contains databases, user decisions,
settings, uploads, cache, logs, and backups. It remains outside the code
release so replacing code cannot overwrite operational data.

## Legacy retirement rule

The legacy `PriceMixer_server_backup_2026-06-01_21-18-50` directory is safe to
archive only after all running process command lines point to the current code
release and its local `.venv`, and both ports `5001` and `5055` pass health
checks. The migration snapshots are rollback artifacts, not active runtime.
