"""Persistent experimental candidate review for products without Onliner IDs."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid

from price_mixer.logging_config import get_logger, log_context


TIER_ORDER_SQL = (
    "CASE confidence_tier "
    "WHEN 'exact' THEN 0 WHEN 'strong' THEN 1 WHEN 'ambiguous' THEN 2 "
    "WHEN 'possible' THEN 3 ELSE 4 END"
)
STRONG_REASONS = {
    "apple_article",
    "motherboard_model",
    "numeric_model",
    "strict_article",
    "tgpc_code_exact",
}
LOGGER = get_logger("price_mixer.jobs.experimental_noid")


def classify_candidates(candidates, *, exact=False):
    active = [item for item in (candidates or []) if not item.get("rejected")]
    if not active:
        return "none", 0.0, 0.0
    top_score = float(active[0].get("score", 0.0) or 0.0)
    second_score = float(active[1].get("score", 0.0) or 0.0) if len(active) > 1 else 0.0
    gap = round(max(0.0, top_score - second_score), 3)
    if exact:
        return "exact", top_score, gap
    if len(active) > 1 and top_score >= 0.84 and gap <= 0.015:
        return "ambiguous", top_score, gap
    reason = str(active[0].get("reason", "") or "")
    if top_score >= 0.97 and reason in STRONG_REASONS and (len(active) == 1 or gap >= 0.02):
        return "strong", top_score, gap
    return "possible", top_score, gap


def _item_key(supplier, name_key):
    raw = f"{str(supplier or '').casefold()}\n{name_key}".encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:24]


class ExperimentalNoIdRuntime:
    def __init__(
        self,
        *,
        db_connection,
        read_dataframe,
        normalize_onliner_id,
        normalize_name_key,
        find_exact,
        find_top_candidates,
        confirm_batch,
        start_thread=None,
        max_workers=8,
    ):
        self.db_connection = db_connection
        self.read_dataframe = read_dataframe
        self.normalize_onliner_id = normalize_onliner_id
        self.normalize_name_key = normalize_name_key
        self.find_exact = find_exact
        self.find_top_candidates = find_top_candidates
        self.confirm_batch = confirm_batch
        self.start_thread = start_thread or self._default_start_thread
        self.max_workers = max(1, min(int(max_workers or 8), 12))
        self.lock = threading.RLock()
        self.active_threads = {}
        self._init_schema()

    @staticmethod
    def _default_start_thread(target):
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        return thread

    def _init_schema(self):
        with self.db_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS experimental_noid_jobs (
                    job_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total INTEGER NOT NULL DEFAULT 0,
                    processed INTEGER NOT NULL DEFAULT 0,
                    message TEXT DEFAULT '',
                    error TEXT DEFAULT '',
                    started_at INTEGER NOT NULL DEFAULT 0,
                    finished_at INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_experimental_noid_jobs_session
                    ON experimental_noid_jobs(session_id, started_at DESC);
                CREATE TABLE IF NOT EXISTS experimental_noid_items (
                    job_id TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    row_idx TEXT DEFAULT '',
                    supplier TEXT DEFAULT '',
                    product_name TEXT NOT NULL,
                    name_key TEXT NOT NULL,
                    category TEXT DEFAULT '',
                    occurrences INTEGER NOT NULL DEFAULT 1,
                    confidence_tier TEXT NOT NULL DEFAULT 'none',
                    decision_state TEXT NOT NULL DEFAULT 'open',
                    top_score REAL NOT NULL DEFAULT 0,
                    score_gap REAL NOT NULL DEFAULT 0,
                    selected_id TEXT DEFAULT '',
                    candidates_json TEXT NOT NULL DEFAULT '[]',
                    created_at INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(job_id, item_key)
                );
                CREATE INDEX IF NOT EXISTS idx_experimental_noid_items_report
                    ON experimental_noid_items(job_id, decision_state, confidence_tier, top_score DESC);
                CREATE INDEX IF NOT EXISTS idx_experimental_noid_items_supplier
                    ON experimental_noid_items(job_id, supplier);
                CREATE INDEX IF NOT EXISTS idx_experimental_noid_items_category
                    ON experimental_noid_items(job_id, category);
                CREATE TABLE IF NOT EXISTS experimental_noid_rejections (
                    supplier TEXT NOT NULL,
                    name_key TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(supplier, name_key, candidate_id)
                );
                """
            )
            conn.execute(
                "UPDATE experimental_noid_jobs SET status='interrupted', "
                "message='Предыдущий запуск был прерван перезапуском.', finished_at=? "
                "WHERE status IN ('queued','running')",
                (int(time.time()),),
            )

    def _latest_job_id(self, session_id):
        with self.db_connection() as conn:
            row = conn.execute(
                "SELECT job_id FROM experimental_noid_jobs WHERE session_id=? "
                "ORDER BY started_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return str(row[0]) if row else ""

    def start(self, session_dir):
        if not session_dir:
            return {"ok": False, "error": "Нет активного прайса."}, 400
        session_id = Path(session_dir).name
        with self.lock:
            for job_id, thread in list(self.active_threads.items()):
                if thread and getattr(thread, "is_alive", lambda: False)():
                    return {"ok": False, "error": "Экспериментальный подбор уже выполняется.", "job_id": job_id}, 409
                self.active_threads.pop(job_id, None)
            job_id = uuid.uuid4().hex[:12]
            now = int(time.time())
            with self.db_connection() as conn:
                conn.execute(
                    "INSERT INTO experimental_noid_jobs "
                    "(job_id,session_id,status,message,started_at) VALUES (?,?,?,?,?)",
                    (job_id, session_id, "queued", "Подготавливаю товары без ID...", now),
                )
            thread = self.start_thread(lambda: self._worker(job_id, str(session_dir)))
            self.active_threads[job_id] = thread
        return {"ok": True, "job_id": job_id, "status": self.status(session_dir, job_id)}, 202

    def _collect_tasks(self, dataframe):
        tasks = {}
        for row_idx, row in dataframe.iterrows():
            if self.normalize_onliner_id(row.get("OnlinerID", "")):
                continue
            name = str(row.get("Название", "") or "").strip()
            if not name:
                continue
            supplier = str(row.get("Поставщик", "") or "").strip()
            name_key = self.normalize_name_key(name)
            if not name_key:
                continue
            key = _item_key(supplier, name_key)
            if key in tasks:
                tasks[key]["occurrences"] += 1
                continue
            tasks[key] = {
                "item_key": key,
                "row_idx": str(row_idx),
                "supplier": supplier,
                "product_name": name,
                "name_key": name_key,
                "category": str(row.get("Категория", "") or "").strip(),
                "occurrences": 1,
            }
        return list(tasks.values())

    def _load_rejections(self):
        out = set()
        with self.db_connection() as conn:
            for row in conn.execute(
                "SELECT supplier,name_key,candidate_id FROM experimental_noid_rejections"
            ).fetchall():
                out.add((str(row[0]).casefold(), str(row[1]), str(row[2])))
        return out

    def _prepare_candidates(self, task, rejection_keys):
        exact = self.find_exact(task["product_name"])
        candidates = []
        exact_id = self.normalize_onliner_id((exact or {}).get("id", ""))
        if exact_id:
            candidates.append({
                "id": exact_id,
                "name": str((exact or {}).get("name", "") or "").strip(),
                "url": str((exact or {}).get("url", "") or "").strip(),
                "score": 1.0,
                "source": "db_exact",
                "reason": "exact_name",
            })
        else:
            candidates = list(self.find_top_candidates(
                task["product_name"],
                top_n=5,
                min_score=0.18,
                allow_b2b=False,
            ) or [])
        seen = set()
        cleaned = []
        for candidate in candidates:
            oid = self.normalize_onliner_id((candidate or {}).get("id", ""))
            if not oid or oid in seen:
                continue
            seen.add(oid)
            rejected = (task["supplier"].casefold(), task["name_key"], oid) in rejection_keys
            cleaned.append({
                "id": oid,
                "name": str((candidate or {}).get("name", "") or "").strip(),
                "url": str((candidate or {}).get("url", "") or "").strip(),
                "score": round(float((candidate or {}).get("score", 0.0) or 0.0), 3),
                "source": str((candidate or {}).get("source", "local_db") or "local_db"),
                "reason": str((candidate or {}).get("reason", "") or ""),
                "rejected": rejected,
            })
        cleaned.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
        tier, top_score, gap = classify_candidates(cleaned, exact=bool(exact_id and not cleaned[0].get("rejected")))
        return cleaned, tier, top_score, gap

    def _store_items(self, job_id, resolved_items):
        if not resolved_items:
            return
        now = int(time.time())
        values = []
        for task, candidates, tier, top_score, gap in resolved_items:
            values.append((
                job_id, task["item_key"], task["row_idx"], task["supplier"], task["product_name"],
                task["name_key"], task["category"], task["occurrences"], tier, top_score, gap,
                json.dumps(candidates, ensure_ascii=False), job_id, task["item_key"], now, now,
            ))
        with self.db_connection() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO experimental_noid_items "
                "(job_id,item_key,row_idx,supplier,product_name,name_key,category,occurrences,"
                "confidence_tier,decision_state,top_score,score_gap,candidates_json,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,'open',?,?,?,COALESCE((SELECT created_at FROM "
                "experimental_noid_items WHERE job_id=? AND item_key=?),?),?)",
                values,
            )

    def _store_item(self, job_id, task, candidates, tier, top_score, gap):
        self._store_items(job_id, [(task, candidates, tier, top_score, gap)])

    def _checkpoint_database(self):
        try:
            with self.db_connection() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass

    def _update_job(self, job_id, **values):
        if not values:
            return
        allowed = {"status", "total", "processed", "message", "error", "finished_at"}
        values = {key: value for key, value in values.items() if key in allowed}
        if not values:
            return
        sql = ",".join(f"{key}=?" for key in values)
        with self.db_connection() as conn:
            conn.execute(f"UPDATE experimental_noid_jobs SET {sql} WHERE job_id=?", [*values.values(), job_id])

    def _worker(self, job_id, session_dir):
        with log_context(job_id=job_id):
            LOGGER.info("experimental no-ID worker started")
            self._run_worker(job_id, session_dir)

    def _run_worker(self, job_id, session_dir):
        try:
            dataframe = self.read_dataframe(session_dir)
            tasks = self._collect_tasks(dataframe)
            total = len(tasks)
            self._update_job(
                job_id,
                status="running",
                total=total,
                processed=0,
                message=f"Найдено {total} товаров без ID.",
            )
            if not tasks:
                self._update_job(
                    job_id,
                    status="completed",
                    message="В текущем прайсе нет товаров без ID.",
                    finished_at=int(time.time()),
                )
                return
            rejection_keys = self._load_rejections()
            processed = 0
            errors = 0
            pending_writes = []

            def resolve(task):
                return task, self._prepare_candidates(task, rejection_keys)

            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                futures = {pool.submit(resolve, task): task for task in tasks}
                for future in as_completed(futures):
                    task = futures[future]
                    try:
                        task, result = future.result()
                        candidates, tier, top_score, gap = result
                    except Exception:
                        errors += 1
                        candidates, tier, top_score, gap = [], "none", 0.0, 0.0
                    pending_writes.append((task, candidates, tier, top_score, gap))
                    processed += 1
                    if len(pending_writes) >= 25 or processed == total:
                        self._store_items(job_id, pending_writes)
                        pending_writes = []
                    if processed == total or processed % 10 == 0:
                        self._update_job(
                            job_id,
                            processed=processed,
                            message=f"Подобрано кандидатов: {processed} из {total}.",
                        )
            self._update_job(
                job_id,
                status="completed",
                processed=total,
                message=(
                    f"Подбор завершён. Обработано {total} товаров без ID."
                    + (f" Ошибок отдельных позиций: {errors}." if errors else "")
                ),
                finished_at=int(time.time()),
            )
            self._checkpoint_database()
        except Exception as exc:
            LOGGER.exception("experimental no-ID worker failed")
            self._update_job(
                job_id,
                status="failed",
                message="Экспериментальный подбор завершился с ошибкой.",
                error=str(exc),
                finished_at=int(time.time()),
            )
            self._checkpoint_database()

    def status(self, session_dir, job_id=""):
        session_id = Path(session_dir).name if session_dir else ""
        job_id = str(job_id or "").strip() or self._latest_job_id(session_id)
        if not job_id:
            return {"ok": True, "job": None}
        with self.db_connection() as conn:
            job = conn.execute(
                "SELECT job_id,session_id,status,total,processed,message,error,started_at,finished_at "
                "FROM experimental_noid_jobs WHERE job_id=? AND session_id=?",
                (job_id, session_id),
            ).fetchone()
            if not job:
                return {"ok": True, "job": None}
            tier_counts = {
                str(row[0]): int(row[1])
                for row in conn.execute(
                    "SELECT confidence_tier,COUNT(*) FROM experimental_noid_items "
                    "WHERE job_id=? AND decision_state='open' GROUP BY confidence_tier",
                    (job_id,),
                ).fetchall()
            }
            decision_counts = {
                str(row[0]): int(row[1])
                for row in conn.execute(
                    "SELECT decision_state,COUNT(*) FROM experimental_noid_items "
                    "WHERE job_id=? GROUP BY decision_state",
                    (job_id,),
                ).fetchall()
            }
            suppliers = [
                {"name": str(row[0]), "count": int(row[1])}
                for row in conn.execute(
                    "SELECT supplier,COUNT(*) FROM experimental_noid_items WHERE job_id=? "
                    "GROUP BY supplier ORDER BY supplier",
                    (job_id,),
                ).fetchall()
            ]
            categories = [
                {"name": str(row[0]), "count": int(row[1])}
                for row in conn.execute(
                    "SELECT category,COUNT(*) FROM experimental_noid_items WHERE job_id=? "
                    "GROUP BY category ORDER BY category",
                    (job_id,),
                ).fetchall()
            ]
        data = dict(job)
        total = int(data.get("total", 0) or 0)
        processed = int(data.get("processed", 0) or 0)
        data["percent"] = int(processed / total * 100) if total else (100 if data.get("status") == "completed" else 0)
        data["tier_counts"] = tier_counts
        data["decision_counts"] = decision_counts
        data["suppliers"] = suppliers
        data["categories"] = categories
        return {"ok": True, "job": data}

    def items(self, session_dir, params):
        session_id = Path(session_dir).name if session_dir else ""
        job_id = str((params or {}).get("job_id", "") or "").strip() or self._latest_job_id(session_id)
        if not job_id:
            return {"ok": True, "items": [], "total": 0, "page": 1, "pages": 0}
        try:
            page = max(1, int((params or {}).get("page", 1) or 1))
            limit = max(10, min(100, int((params or {}).get("limit", 40) or 40)))
        except (TypeError, ValueError):
            page, limit = 1, 40
        clauses = ["i.job_id=?", "j.session_id=?"]
        values = [job_id, session_id]
        for field in ("supplier", "category", "confidence_tier", "decision_state"):
            value = str((params or {}).get(field, "") or "").strip()
            if value:
                clauses.append(f"i.{field}=?")
                values.append(value)
        query = str((params or {}).get("query", "") or "").strip()
        if query:
            clauses.append("(lower(i.product_name) LIKE ? OR i.candidates_json LIKE ?)")
            values.extend([f"%{query.casefold()}%", f"%{query}%"])
        where = " AND ".join(clauses)
        with self.db_connection() as conn:
            total = int(conn.execute(
                "SELECT COUNT(*) FROM experimental_noid_items i "
                "JOIN experimental_noid_jobs j ON j.job_id=i.job_id WHERE " + where,
                values,
            ).fetchone()[0] or 0)
            rows = conn.execute(
                "SELECT i.* FROM experimental_noid_items i "
                "JOIN experimental_noid_jobs j ON j.job_id=i.job_id WHERE " + where + " "
                f"ORDER BY {TIER_ORDER_SQL}, i.top_score DESC, i.product_name "
                "LIMIT ? OFFSET ?",
                [*values, limit, (page - 1) * limit],
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item["candidates"] = json.loads(item.pop("candidates_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                item["candidates"] = []
                item.pop("candidates_json", None)
            items.append(item)
        pages = (total + limit - 1) // limit if total else 0
        return {"ok": True, "job_id": job_id, "items": items, "total": total, "page": page, "pages": pages}

    def decide(self, session_dir, payload):
        if not session_dir:
            return {"ok": False, "error": "Нет активного прайса."}, 400
        payload = payload if isinstance(payload, dict) else {}
        job_id = str(payload.get("job_id", "") or "").strip()
        item_key = str(payload.get("item_key", "") or "").strip()
        action = str(payload.get("action", "") or "").strip()
        session_id = Path(session_dir).name
        with self.db_connection() as conn:
            row = conn.execute(
                "SELECT i.* FROM experimental_noid_items i JOIN experimental_noid_jobs j ON j.job_id=i.job_id "
                "WHERE i.job_id=? AND i.item_key=? AND j.session_id=?",
                (job_id, item_key, session_id),
            ).fetchone()
        if not row:
            return {"ok": False, "error": "Позиция отчёта не найдена."}, 404
        item = dict(row)
        candidates = json.loads(item.get("candidates_json") or "[]")
        if action == "confirm":
            candidate_id = self.normalize_onliner_id(payload.get("candidate_id", ""))
            candidate = next((entry for entry in candidates if self.normalize_onliner_id(entry.get("id")) == candidate_id), None)
            if not candidate_id or not candidate:
                return {"ok": False, "error": "Кандидат не найден в отчёте."}, 400
            result = self.confirm_batch(session_dir, {
                "source": "experimental_noid_review",
                "items": [{
                    "row_idx": item.get("row_idx"),
                    "name": item.get("product_name"),
                    "supplier": item.get("supplier"),
                    "onliner_id": candidate_id,
                    "url": str(candidate.get("url", "") or ""),
                }],
            })
            body, status_code = result if isinstance(result, tuple) else (result, 200)
            if status_code >= 400 or str((body or {}).get("status", "")) != "ok":
                return body, status_code
            with self.db_connection() as conn:
                conn.execute(
                    "UPDATE experimental_noid_items SET decision_state='confirmed',selected_id=?,updated_at=? "
                    "WHERE job_id=? AND item_key=?",
                    (candidate_id, int(time.time()), job_id, item_key),
                )
            return {"ok": True, "status": "confirmed", "selected_id": candidate_id}
        if action == "reject_candidate":
            candidate_id = self.normalize_onliner_id(payload.get("candidate_id", ""))
            changed = False
            for candidate in candidates:
                if self.normalize_onliner_id(candidate.get("id")) == candidate_id:
                    candidate["rejected"] = True
                    changed = True
            if not changed:
                return {"ok": False, "error": "Кандидат не найден в отчёте."}, 400
            tier, top_score, gap = classify_candidates(candidates)
            with self.db_connection() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO experimental_noid_rejections "
                    "(supplier,name_key,candidate_id,created_at) VALUES (?,?,?,?)",
                    (item.get("supplier", "").casefold(), item.get("name_key", ""), candidate_id, int(time.time())),
                )
                conn.execute(
                    "UPDATE experimental_noid_items SET candidates_json=?,confidence_tier=?,top_score=?,score_gap=?,updated_at=? "
                    "WHERE job_id=? AND item_key=?",
                    (json.dumps(candidates, ensure_ascii=False), tier, top_score, gap, int(time.time()), job_id, item_key),
                )
            return {"ok": True, "status": "rejected", "candidate_id": candidate_id}
        if action == "skip":
            with self.db_connection() as conn:
                conn.execute(
                    "UPDATE experimental_noid_items SET decision_state='skipped',updated_at=? "
                    "WHERE job_id=? AND item_key=?",
                    (int(time.time()), job_id, item_key),
                )
            return {"ok": True, "status": "skipped"}
        return {"ok": False, "error": "Неизвестное действие."}, 400
