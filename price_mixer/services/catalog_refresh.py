"""Durable import cadence and a shared web/worker lease."""

import json
import time
import uuid


WEEK = 7 * 24 * 60 * 60
RETRY_DELAY = 60 * 60
LEASE_SECONDS = 6 * 60 * 60


def save_import_summary(conn, summary):
    conn.execute("CREATE TABLE IF NOT EXISTS catalog_import_summary (singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL)")
    conn.execute("INSERT OR REPLACE INTO catalog_import_summary VALUES (1, ?)", (json.dumps(summary),))


def last_import_summary(conn):
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'catalog_import_summary' in tables:
        row = conn.execute("SELECT payload FROM catalog_import_summary WHERE singleton=1").fetchone()
        if row:
            return json.loads(row[0])
    if 'catalog_refresh_state' in tables:
        row = conn.execute("SELECT last_success, status_json FROM catalog_refresh_state WHERE singleton=1").fetchone()
        if row and row[0]:
            status = json.loads(row[1])
            return {'finished_at': row[0], 'inserted': status.get('inserted') if status.get('finished_at') == row[0] else None, 'updated': None}
    return None


class CatalogRefreshState:
    def __init__(self, connection):
        self.connection = connection

    def _init(self, conn):
        conn.execute("""CREATE TABLE IF NOT EXISTS catalog_refresh_state (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            token TEXT NOT NULL DEFAULT '', lease_until INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT '', success_source TEXT NOT NULL DEFAULT '',
            last_success INTEGER NOT NULL DEFAULT 0, last_attempt INTEGER NOT NULL DEFAULT 0,
            status_json TEXT NOT NULL DEFAULT '{}'
        )""")
        conn.execute("INSERT OR IGNORE INTO catalog_refresh_state(singleton) VALUES (1)")

    def claim(self, source, *, automatic=False, now=None):
        now = int(time.time() if now is None else now)
        with self.connection() as conn:
            self._init(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM catalog_refresh_state WHERE singleton=1").fetchone()
            if row['lease_until'] > now:
                return None, 'already_running'
            if automatic and row['success_source'] == source and row['last_success'] > now - WEEK:
                return None, 'fresh'
            if automatic and row['source'] == source and row['last_attempt'] > now - RETRY_DELAY:
                return None, 'retry_later'
            token = uuid.uuid4().hex
            status = {"running": True, "percent": 0, "message": "Обновляю каталог GSheets в фоне…"}
            conn.execute("""UPDATE catalog_refresh_state SET token=?, lease_until=?, source=?,
                last_attempt=?, status_json=? WHERE singleton=1""",
                (token, now + LEASE_SECONDS, source, now, json.dumps(status)))
            return token, 'started'

    def finish(self, token, *, success, status, now=None):
        now = int(time.time() if now is None else now)
        with self.connection() as conn:
            conn.execute("""UPDATE catalog_refresh_state SET token='', lease_until=0,
                last_success=CASE WHEN ? THEN ? ELSE last_success END,
                success_source=CASE WHEN ? THEN source ELSE success_source END,
                status_json=? WHERE singleton=1 AND token=?""",
                (success, now, success, json.dumps(dict(status), ensure_ascii=False), token))

    def status(self, now=None):
        now = int(time.time() if now is None else now)
        with self.connection() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_refresh_state'").fetchone():
                return {}
            row = conn.execute("SELECT * FROM catalog_refresh_state WHERE singleton=1").fetchone()
        if row is None:
            return {}
        status = json.loads(row['status_json'])
        if status.get('running') and row['lease_until'] <= now:
            status.update(running=False, message="Импорт прерван. Обновление повторится после обработки прайса.")
        return status
