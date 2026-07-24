# Price Mixer migration acceptance

Date: 2026-07-24

## Safety boundary

- The working local mixer remains unchanged on `127.0.0.1:5001`.
- Development uses the separate `codex/migration-complete` branch.
- Durable state was copied from a verified backup, never moved.
- Secrets are not included in the Git repository or verified runtime backup.

## Runtime verification

- Verified backup objects: 14/14, including the indexed session-products store.
- SQLite `quick_check`: `ok`.
- Catalog rows: 801,971.
- Name variants: 798,602.
- Manual ID bindings: 15,254.
- Supplier-scoped manual bindings: 15,254; legacy unscoped: 0.
- All copied state/data and upload session files match their source hashes.
- Real session counters match the working mixer:
  - visible rows: 12,847;
  - without ID: 1,801;
  - duplicate-ID rows: 2,332;
  - export rows: 9,813;
  - hidden rows: 11,262.

## Usage scenario matrix

| Scenario | Expected result | Automated guard |
| --- | --- | --- |
| Same product and ID across suppliers | Allowed and isolated | `test_confirm_allows_same_id_already_bound_to_another_supplier` |
| Conflicting ID inside one supplier | Blocked with existing product details | `test_confirm_blocks_hidden_duplicate_in_same_supplier_durable_cache` |
| Same name across IVEN/IVEN_zakaz/Tradex | Separate bindings | `test_confirm_manual_id_batch_keeps_same_name_separate_by_supplier` |
| Reload a new supplier price | Supplier-scoped ID returns | `test_all_supplier_scoped_manual_bindings_are_allowed_on_reload` |
| Clear a wrong ID | Row, cache and queue are cleared safely | `test_clear_manual_id_clears_row_blocks_binding_and_cleans_cache_queue` |
| Roll back the last ID edit | Row and durable binding are restored | `test_rollback_removes_new_durable_binding_so_it_cannot_return_on_reload` |
| Same ID at different supplier prices | Lowest export price wins | `test_apply_export_keep_lowest_price_per_onliner_id_keeps_non_id_rows` |
| Google Sheets replacement | Existing worksheet ID is preserved | `test_export_google_sheets_payload_preserves_existing_sheet_id` |
| N-Tech and IVEN PC matching | Supplier-scoped exact-code workflow | `test_run_tgpc_pc_worker_can_target_iven_pc_supplier_only` |
| Restarted XLSX work | Durable queue lease/retry recovers | `test_durable_jobs.py`, `test_background_xlsx.py` |
| Browser upload/result/download | Complete isolated web+worker flow | `tests/e2e/app-smoke.spec.js` |

## PC matching audit

The dry-run audit did not change any ID.

| Supplier | Existing IDs checked | Exact code matches | Mismatches | Without ID | Catalog candidate |
| --- | ---: | ---: | ---: | ---: | ---: |
| N-Tech | 1,203 | 1,203 | 0 | 110 | 0 |
| IVEN | 1,230 | 1,230 | 0 | 844 | 0 |

Ten IVEN rows share one supplier code across different configurations and are
blocked as ambiguous. The remaining products have no matching code in the
current local Onliner catalog, so automatic assignment correctly leaves them
for a future catalog refresh/manual review.

## Performance acceptance

Synthetic benchmark results are written by `scripts/benchmark_local.py`.

- 25k rows: cold page about 50 ms; repeated page p95 below 1 ms internally.
- 100k rows: cold page about 200 ms; repeated page p95 below 1 ms internally.
- 100k full payload: about 10.3 MB; paged payload: about 12 KB.
- Real 33,223-row session: warm HTTP page/search about 17 ms.
- Static assets use a five-minute browser cache; API and HTML remain no-store.

The canonical session-products read model adds indexed SQL paging and FTS5
search while retaining the JSON compatibility snapshot:

- real 12,847-row parity: 6/6 page, sort, search, no-ID and duplicate scenarios;
- 100k rows: page p95 2.7 ms and FTS search p95 25.2 ms internally;
- a changed 100k-row revision is indexed in about 1.7 seconds;
- the existing compatibility engine is used automatically if sync/parity fails.

The experimental no-ID review now caches candidate extraction by catalog
revision and normalized product/category key. On 200 real current-price
products, the first pass took 17.2 seconds and the repeated pass 81 ms
(200/200 cache hits). Rejections and confirmations remain supplier-scoped.
Human decisions are recorded for precision and false-positive reporting by
category; automatic confirmation remains disabled.

## Automated verification

- Python: 784 tests passed.
- JavaScript syntax: all application and E2E JavaScript files passed.
- Playwright E2E: 3/3 passed with isolated web and external durable worker.

## Parallel acceptance

- Legacy mixer remains available at `http://127.0.0.1:5001`.
- Candidate mixer is available at `http://127.0.0.1:5012`.
- Candidate web and durable worker pass authenticated production smoke 4/4.
- A real session matches the legacy counters for without-ID, duplicate-ID,
  export, and hidden rows.
- Real XLSX download succeeds and opens as an OOXML workbook.
- The stop/start cycle was exercised: candidate processes and port stop
  cleanly while the legacy mixer remains available, then restart successfully.
- Secrets are ignored by Git and stored with owner-only file permissions.

The existing local password remains valid on both instances. It is shorter
than the 12-character production policy, so a future public/server cutover
must rotate it before production preflight; the local candidate was not
silently given a different password.
