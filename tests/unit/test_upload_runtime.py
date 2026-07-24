from pathlib import Path

import pytest

from price_mixer.services.upload_runtime import UploadRuntime


class Upload:
    def __init__(self, filename):
        self.filename = filename


class Logger:
    def info(self, *_args):
        return None


def runtime(tmp_path, *, processor=None, removed=None):
    session_dir = tmp_path / "session"
    removed = removed if removed is not None else []
    processor = processor or (
        lambda _entries, **_kwargs: {
            "session_id": "session",
            "session_dir": session_dir,
            "output_path": session_dir / "result.xlsx",
        }
    )
    return UploadRuntime(
        create_session_dir=lambda: ("session", session_dir),
        load_app_settings=lambda: {"ok": True},
        build_file_entries=lambda files, _form, _directory, _settings, _infer: [
            {"filename": item.filename} for item in files
        ],
        infer_supplier_from_filename=lambda _name, _settings=None: "IVEN",
        process_supplier_files=processor,
        remove_session_dir=lambda path: removed.append(Path(path)),
        logger=Logger(),
    )


def test_upload_runtime_rejects_empty_file_list(tmp_path):
    with pytest.raises(ValueError, match="Не загружено"):
        runtime(tmp_path).process([], {})


def test_upload_runtime_returns_normalized_result(tmp_path):
    result = runtime(tmp_path).process([Upload("iven.xlsx")], {})

    assert result.session_id == "session"
    assert result.session_dir == tmp_path / "session"
    assert result.output_path.name == "result.xlsx"


def test_upload_runtime_removes_partial_session_on_failure(tmp_path):
    removed = []

    def fail(_entries, **_kwargs):
        raise RuntimeError("broken")

    with pytest.raises(RuntimeError, match="broken"):
        runtime(tmp_path, processor=fail, removed=removed).process(
            [Upload("iven.xlsx")],
            {},
        )

    assert removed == [tmp_path / "session"]
