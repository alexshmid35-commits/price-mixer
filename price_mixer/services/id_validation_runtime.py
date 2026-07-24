"""Runtime facade for Onliner ID validation job start/status endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from price_mixer.services import id_validation


@dataclass(frozen=True)
class IdValidationRuntime:
    get_active_session_dir: Callable[[], str | None]
    verify_status: dict
    verify_lock: object
    validate_status: dict
    validate_lock: object
    verify_worker: Callable
    validate_api_worker: Callable
    validate_db_worker: Callable
    thread_factory: Callable
    isolated_verify_start: Callable | None = None
    isolated_verify_status: Callable | None = None
    before_validate_start: Callable | None = None
    cancel_validate: Callable | None = None

    def verify_all_start(self):
        if callable(self.isolated_verify_start):
            return self.isolated_verify_start()
        return id_validation.start_validation_job(
            self.get_active_session_dir(),
            self.verify_status,
            self.verify_lock,
            id_validation.build_verify_all_start_state(),
            self.verify_worker,
            self.thread_factory,
        )

    def verify_all_status(self):
        if callable(self.isolated_verify_status):
            return self.isolated_verify_status()
        return id_validation.verify_all_status_snapshot(self.verify_status, self.verify_lock)

    def validate_clean_start(self):
        return id_validation.start_validation_job(
            self.get_active_session_dir(),
            self.validate_status,
            self.validate_lock,
            id_validation.build_validate_clean_start_state("api"),
            self.validate_api_worker,
            self.thread_factory,
            before_start=self.before_validate_start,
        )

    def validate_clean_db_start(self):
        return id_validation.start_validation_job(
            self.get_active_session_dir(),
            self.validate_status,
            self.validate_lock,
            id_validation.build_validate_clean_start_state("db"),
            self.validate_db_worker,
            self.thread_factory,
            before_start=self.before_validate_start,
        )

    def validate_clean_status(self):
        return id_validation.status_snapshot(self.validate_status, self.validate_lock)

    def validate_clean_cancel(self):
        return id_validation.cancel_validation_job(
            self.get_active_session_dir(),
            self.validate_status,
            self.validate_lock,
            self.cancel_validate,
        )
