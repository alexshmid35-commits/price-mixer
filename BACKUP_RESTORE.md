# Price Mixer backup and restore

The backup tool is intentionally conservative. It creates new backup
directories, verifies every copied file, and only produces restore plans. It
does not overwrite or restore application files automatically.

## What is included

The source list comes from `runtime_hygiene.ARTIFACT_POLICIES` and
`RUNTIME_LAYOUT.md`.

Default backup:

- every existing durable state file marked `backup_required`;
- `onliner_products.db` through the SQLite online backup API;
- a manifest containing owner, category, size, and SHA-256.

Excluded by default:

- rebuildable caches;
- uploads and logs;
- old backups;
- `.env` and Google service-account files.

Secrets are copied under `secrets/` only with the explicit
`--include-secrets` option. In production, secrets should normally be backed
up separately in an encrypted secret store.

## Create

Stop write-heavy user activity where practical, then choose a new,
non-existing destination:

```bash
.venv/bin/python deploy/backup_restore.py create \
  /srv/price-mixer-backups/2026-07-23T2300
```

The source database may remain open: SQLite's backup API creates a consistent
snapshot of committed data. The destination is first written as a `.partial`
directory, verified, and only then renamed to its final name.

To include local secrets explicitly:

```bash
.venv/bin/python deploy/backup_restore.py create \
  /secure-backups/price-mixer-2026-07-23 \
  --include-secrets
```

The service-account file configured outside the project directory is not
collected automatically. Back it up through the protected system secret
backup process.

## Verify

```bash
.venv/bin/python deploy/backup_restore.py verify \
  /srv/price-mixer-backups/2026-07-23T2300
```

Verification checks:

- manifest format and safe relative paths;
- file presence and size;
- SHA-256 for every file;
- `PRAGMA quick_check` for SQLite.

Verification is read-only.

## Restore dry-run

```bash
.venv/bin/python deploy/backup_restore.py restore-plan \
  /srv/price-mixer-backups/2026-07-23T2300 \
  /opt/price-mixer/current
```

The result lists `create` and `replace` actions. It does not create, replace,
move, or delete target files. Secrets are omitted unless
`--include-secrets` is explicitly supplied.

## Manual restore procedure

Automatic restore is intentionally not implemented yet. A controlled restore
must:

1. verify the backup;
2. stop Price Mixer and confirm no background worker remains;
3. take a safety backup of the current state;
4. review the generated restore plan;
5. restore state and database into a staging directory;
6. run SQLite integrity checks and a small application smoke test;
7. switch paths only after validation;
8. retain both the pre-restore and source backups.

Never restore only SQLite while leaving newer JSON state in place without
checking their migration revisions.

## Daily systemd schedule

Production templates:

- `deploy/price-mixer-backup.service`;
- `deploy/price-mixer-backup.timer`;
- `deploy/scheduled_backup.py`.

The timer runs daily around 03:15 with a randomized delay and `Persistent=true`,
so a missed run is started after the server returns. Every run creates a new
timestamped directory, uses SQLite online backup, checks SHA-256 and performs
an independent verification pass. Secrets are never included.

Install after creating the external directory:

```bash
sudo install -d -o price-mixer -g price-mixer -m 0750 \
  /srv/price-mixer-backups
sudo install -m 0644 deploy/price-mixer-backup.service \
  /etc/systemd/system/price-mixer-backup.service
sudo install -m 0644 deploy/price-mixer-backup.timer \
  /etc/systemd/system/price-mixer-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now price-mixer-backup.timer
sudo systemctl list-timers price-mixer-backup.timer
```

Manual first run:

```bash
sudo systemctl start price-mixer-backup.service
sudo systemctl status price-mixer-backup.service
journalctl -u price-mixer-backup.service -n 100 --no-pager
```

The templates intentionally do not delete old backups. Retention must be
configured only after a protected external copy and a restore drill are
confirmed. Monitor free space and the timer's last successful run.
