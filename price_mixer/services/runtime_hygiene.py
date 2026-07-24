"""Non-destructive runtime artifact and secret hygiene checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArtifactPolicy:
    category: str
    owner: str
    backup_required: bool
    sensitive: bool = False
    description: str = ""


ARTIFACT_POLICIES = {
    "app_settings.json": ArtifactPolicy(
        "state", "price_mixer.settings", True,
        description="User-facing application settings.",
    ),
    "auto_refresh_settings.json": ArtifactPolicy(
        "state", "price_mixer.settings", True,
        description="Automatic market refresh schedule.",
    ),
    "onliner_api_settings.json": ArtifactPolicy(
        "state", "price_mixer.settings", True, sensitive=True,
        description="Onliner API and proxy settings; proxy URLs may be sensitive.",
    ),
    "category_markups.json": ArtifactPolicy(
        "state", "price_mixer.services.category_config", True,
        description="Saved category pricing rules.",
    ),
    "category_overrides.json": ArtifactPolicy(
        "state", "price_mixer.services.category_config", True,
        description="Effective category override state.",
    ),
    "manual_category_overrides.json": ArtifactPolicy(
        "state", "price_mixer.services.category_config", True,
        description="Explicit user category decisions.",
    ),
    "category_visibility.json": ArtifactPolicy(
        "state", "price_mixer.services.category_state_store", True,
        description="Globally hidden categories.",
    ),
    "manual_id_bindings.json": ArtifactPolicy(
        "state", "price_mixer.services.manual_id_store", True,
        description="Explicit user Onliner ID decisions.",
    ),
    "id_change_journal.json": ArtifactPolicy(
        "state", "price_mixer.services.manual_id_store", True,
        description="Rollback journal for manual ID changes.",
    ),
    "id_review_queue.json": ArtifactPolicy(
        "state", "price_mixer.services.review_queue_store", True,
        description="Unresolved manual ID review queue.",
    ),
    "supplier_snapshots.json": ArtifactPolicy(
        "state", "price_mixer.services.supplier_snapshots", True,
        description="Historical supplier snapshots used for change detection.",
    ),
    "api_fetch_history.json": ArtifactPolicy(
        "state", "price_mixer.services.supplier_snapshots", True,
        description="API supplier fetch history.",
    ),
    "onliner_cache.json": ArtifactPolicy(
        "cache", "price_mixer.services._legacy", False,
        description="Rebuildable catalog lookup cache.",
    ),
    "onliner_id_cache.json": ArtifactPolicy(
        "cache", "price_mixer.services._legacy", False,
        description="Rebuildable automatic Onliner ID match cache.",
    ),
    "onliner_market_cache.json": ArtifactPolicy(
        "cache", "price_mixer.services.onliner_market", False,
        description="Rebuildable market price cache.",
    ),
    "onliner_product_cache.json": ArtifactPolicy(
        "cache", "price_mixer.services.onliner_market", False,
        description="Rebuildable Onliner product metadata cache.",
    ),
    "onliner_products.db": ArtifactPolicy(
        "data", "price_mixer.db", True,
        description="Primary local Onliner catalog and SQLite-backed state.",
    ),
    "session_products.db": ArtifactPolicy(
        "data", "price_mixer.services.session_products", True,
        description="Canonical indexed working rows for supplier-price sessions.",
    ),
    "jobs.db": ArtifactPolicy(
        "runtime", "price_mixer.workers.durable_worker", False,
        description="Durable queue state; jobs are reproducible operational work.",
    ),
}

SECRET_FILENAMES = {".env", ".env.local"}
SECRET_PATTERNS = ("ai2025-",)
RUNTIME_SUFFIXES = (".pid", ".log", ".tmp")
RUNTIME_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "logs",
    "playwright-report",
    "test-results",
    "uploads",
}
BACKUP_DIR_NAMES = {"backups"}
BACKUP_MARKERS = (".backup", ".before_")
STATE_FILENAMES = {
    name for name, policy in ARTIFACT_POLICIES.items()
    if policy.category == "state"
}
CACHE_FILENAMES = {
    name for name, policy in ARTIFACT_POLICIES.items()
    if policy.category == "cache"
}
DATA_SUFFIXES = (".db", ".sqlite", ".sqlite-shm", ".sqlite-wal", ".xlsx", ".xls", ".csv")


def get_artifact_policy(path: Path, root: Path) -> ArtifactPolicy | None:
    path = Path(path)
    name = path.name
    rel_parts = (
        path.relative_to(root).parts
        if path.is_relative_to(root)
        else path.parts
    )
    if (
        name in SECRET_FILENAMES
        or name.startswith(".env.")
        or any(
            name.startswith(prefix) and name.endswith(".json")
            for prefix in SECRET_PATTERNS
        )
    ):
        return ArtifactPolicy(
            "secrets",
            "environment/config",
            True,
            sensitive=True,
            description="Credentials or secret configuration.",
        )
    if any(part in RUNTIME_DIR_NAMES for part in rel_parts):
        return ArtifactPolicy(
            "runtime",
            "runtime",
            False,
            description="Temporary or reproducible runtime artifact.",
        )
    if any(part in BACKUP_DIR_NAMES for part in rel_parts) or any(
        marker in name for marker in BACKUP_MARKERS
    ):
        return ArtifactPolicy(
            "backup",
            "backup/restore",
            True,
            sensitive=name.endswith(".json"),
            description="Point-in-time safety copy; never clean automatically.",
        )
    declared = ARTIFACT_POLICIES.get(name)
    if declared is not None:
        return declared
    if name.startswith("onliner_id_cache") and name.endswith(".json"):
        return ArtifactPolicy(
            "cache",
            "price_mixer.services._legacy",
            False,
            description="Rebuildable automatic Onliner ID match cache.",
        )
    if name.startswith("id_mismatch_report") and name.endswith(".json"):
        return ArtifactPolicy(
            "runtime",
            "id validation reports",
            False,
            description="Generated diagnostic report.",
        )
    if path.is_dir() and name in RUNTIME_DIR_NAMES:
        return ArtifactPolicy("runtime", "runtime", False)
    if name.endswith(RUNTIME_SUFFIXES):
        return ArtifactPolicy("runtime", "runtime", False)
    if name.endswith(DATA_SUFFIXES) or ".db-" in name:
        return ArtifactPolicy(
            "data",
            "application data",
            True,
            description="Database or user/import/export data.",
        )
    return None


def classify_project_artifact(path: Path, root: Path) -> str | None:
    policy = get_artifact_policy(path, root)
    return policy.category if policy is not None else None


def collect_project_hygiene(root, *, max_items_per_group=200):
    root = Path(root)
    result = {
        "secrets": [],
        "state": [],
        "cache": [],
        "data": [],
        "backup": [],
        "runtime": [],
    }
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        category = classify_project_artifact(path, root)
        if not category:
            continue
        bucket = result[category]
        if len(bucket) < int(max_items_per_group):
            bucket.append(path.relative_to(root).as_posix())
    return result
