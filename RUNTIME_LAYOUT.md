# Price Mixer runtime layout

This document records the ownership and recovery policy of runtime files.
Local development keeps the historical project-root paths by default.
Production can select physically separated paths through environment
variables. Existing files are never moved automatically.

## Durable state

Durable state represents user decisions or operational history. It must be
included in backups and must never be removed by cache or runtime cleanup.

| File | Owner | Purpose |
| --- | --- | --- |
| `app_settings.json` | `price_mixer.settings` | User-facing application settings |
| `auto_refresh_settings.json` | `price_mixer.settings` | Market refresh schedule |
| `onliner_api_settings.json` | `price_mixer.settings` | API and proxy settings; treat as sensitive |
| `category_markups.json` | `category_config` | Saved category pricing rules |
| `category_overrides.json` | `category_config` | Effective category overrides |
| `manual_category_overrides.json` | `category_config` | Explicit user category decisions |
| `category_visibility.json` | `category_state_store` | Hidden category choices |
| `manual_id_bindings.json` | `manual_id_store` | Explicit user Onliner ID decisions |
| `id_change_journal.json` | `manual_id_store` | Manual ID rollback journal |
| `id_review_queue.json` | `review_queue_store` | Unresolved manual review queue |
| `supplier_snapshots.json` | `supplier_snapshots` | Supplier change history |
| `api_fetch_history.json` | `supplier_snapshots` | API fetch history |

Several state stores are now SQLite-primary and use these JSON files as
migration or fallback sources. That does not make the JSON files safe to
delete.

## Rebuildable cache

Cache may be regenerated from supplier data, Onliner APIs, or the local
catalog. It is excluded from the minimum backup set, although keeping it can
reduce recovery time.

| File or pattern | Owner |
| --- | --- |
| `onliner_cache.json` | legacy catalog lookup |
| `onliner_id_cache.json` (and generated variants) | automatic Onliner ID matching |
| `onliner_market_cache.json` | `onliner_market` |
| `onliner_product_cache.json` | `onliner_market` |

Manual choices must only live in the durable state files above, never solely
in these caches.

## Primary data

`onliner_products.db` is the primary local catalog and also contains
SQLite-backed state. It requires a consistent database backup. SQLite
`-wal`/`-shm` companions must be handled as part of that backup procedure.

Spreadsheet and CSV files outside temporary upload sessions are classified as
data because they may be user inputs or generated deliverables.

## Temporary runtime

The following are temporary or reproducible:

- `uploads/` session directories, including consolidated working files;
- `logs/` and `*.log`;
- `*.pid` and `*.tmp`;
- `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`;
- `playwright-report/` and `test-results/`;
- generated `id_mismatch_report*.json`.
- `jobs.db` — durable operational queue; задания восстанавливаются после
  рестарта, но сама очередь не входит в backup пользовательского state.

Runtime cleanup must remain bounded by the existing session-retention rules.
It must not scan durable state, primary data, secrets, or backups.

## Secrets

The following are sensitive and must be backed up separately with restricted
access:

- `.env` and `.env.*`;
- `ai2025-*.json` Google service-account files;
- `onliner_api_settings.json` when proxy URLs contain credentials.

Secrets must not be printed in diagnostics or copied into session context
documents.

## Backups

`backups/`, `*.backup*`, and `*.before_*` are classified as backup artifacts.
Only timestamped scheduled backups are candidates for automatic retention.
The scheduler keeps seven daily and four weekly verified restore points by
default. A directory that fails manifest/hash/SQLite verification is reported
and never removed automatically.

## Production directories

The path layer supports:

| Variable | Recommended path |
| --- | --- |
| `PRICE_MIXER_STATE_DIR` | `/var/lib/price-mixer/state` |
| `PRICE_MIXER_DATA_DIR` | `/var/lib/price-mixer/data` |
| `PRICE_MIXER_CACHE_DIR` | `/var/cache/price-mixer` |
| `PRICE_MIXER_UPLOAD_DIR` | `/var/lib/price-mixer/uploads` |
| `PRICE_MIXER_LOG_DIR` | `/var/log/price-mixer` |
| `PRICE_MIXER_BACKUP_DIR` | `/srv/price-mixer-backups` |

`deploy/migrate_runtime_layout.py plan` is read-only. The `copy` command:

- requires `--confirm-service-stopped`;
- copies only durable state and primary data;
- uses SQLite online backup and verifies the target;
- refuses existing targets;
- never removes legacy source files.

Recommended migration sequence:

1. create and verify a backup;
2. stop the application and workers;
3. run `plan` and inspect every action;
4. run `copy --confirm-service-stopped`;
5. configure the new absolute paths;
6. run production preflight and start the service;
7. keep the legacy files until acceptance and rollback expiry.
