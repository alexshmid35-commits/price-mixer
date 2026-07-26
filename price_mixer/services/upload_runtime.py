"""Application-level orchestration for manual supplier uploads."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class UploadInputError(ValueError):
    """The submitted upload is missing or has invalid file metadata."""


class UploadProcessingError(RuntimeError):
    """Supplier parsing or consolidation failed after accepting the upload."""


@dataclass(frozen=True)
class UploadResult:
    session_id: str
    session_dir: Path
    output_path: Path


@dataclass(frozen=True)
class UploadRuntime:
    create_session_dir: Callable[[], tuple[str, Path]]
    load_app_settings: Callable[[], dict]
    build_file_entries: Callable
    infer_supplier_from_filename: Callable
    process_supplier_files: Callable
    remove_session_dir: Callable[[Path], None]
    logger: Any

    def process(self, files, form) -> UploadResult:
        usable_files = [item for item in files or [] if item and item.filename]
        self.logger.info("upload received file_count=%s", len(usable_files))
        if not usable_files:
            raise UploadInputError("Не загружено ни одного файла")

        session_id, session_dir = self.create_session_dir()
        try:
            entries = self.build_file_entries(
                usable_files,
                form,
                session_dir,
                self.load_app_settings(),
                self.infer_supplier_from_filename,
            )
        except ValueError as exc:
            self.remove_session_dir(session_dir)
            raise UploadInputError(str(exc)) from exc

        try:
            result = self.process_supplier_files(
                entries,
                session_id=session_id,
                session_dir=session_dir,
            )
        except Exception as exc:
            self.remove_session_dir(session_dir)
            raise UploadProcessingError(str(exc)) from exc

        return UploadResult(
            session_id=str(result["session_id"]),
            session_dir=Path(result["session_dir"]),
            output_path=Path(result["output_path"]),
        )
