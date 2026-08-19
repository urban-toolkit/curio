"""DEC-057 retention declaration + sweep (memos dev/87/88).

The honesty contract: durations exist only when the operator declares them —
absent/corrupt declarations mean NO automatic expiry and an undeclared backup
posture; the sweep enforces only declared values and archives the append-only
ledger by moving files, never rewriting them.
"""

from __future__ import annotations

import json
from datetime import date

from utk_curio.backend.app.agents import retention


def _write_declaration(tmp_path, payload) -> None:
    curio = tmp_path / ".curio"
    curio.mkdir(parents=True, exist_ok=True)
    target = curio / retention.RETENTION_FILENAME
    if isinstance(payload, str):
        target.write_text(payload, encoding="utf-8")
    else:
        target.write_text(json.dumps(payload), encoding="utf-8")


class TestDeclaration:
    def test_absent_file_means_no_declared_retention(self, tmp_curio):
        assert retention.load_declaration() == {}
        assert retention.public_declaration() == {
            "backups": None,
            "ledgerArchiveAfterDays": None,
            "closureGraceDays": None,
        }

    def test_corrupt_file_reads_as_empty(self, tmp_curio):
        _write_declaration(tmp_curio, "{not json")
        assert retention.load_declaration() == {}
        assert retention.backup_posture() is None

    def test_declared_values_surface_in_the_public_shape(self, tmp_curio):
        _write_declaration(tmp_curio, {
            "backups": {"expiryDays": 30},
            "ledger": {"archiveAfterDays": 365},
            "closure": {"graceDays": 14},
        })
        assert retention.public_declaration() == {
            "backups": {"expiryDays": 30},
            "ledgerArchiveAfterDays": 365,
            "closureGraceDays": 14,
        }
        _write_declaration(tmp_curio, {"backups": "none"})
        assert retention.public_declaration()["backups"] == "none"

    def test_invalid_values_read_as_undeclared_never_guessed(self, tmp_curio):
        _write_declaration(tmp_curio, {
            "backups": {"expiryDays": -3},
            "ledger": {"archiveAfterDays": "soon"},
            "closure": {"graceDays": True},
        })
        assert retention.public_declaration() == {
            "backups": None,
            "ledgerArchiveAfterDays": None,
            "closureGraceDays": None,
        }

    def test_unknown_keys_warn_loudly(self, tmp_curio, caplog):
        _write_declaration(tmp_curio, {"transcripts": {"maxAgeDays": 9}})
        with caplog.at_level("WARNING"):
            retention.load_declaration()
        assert "transcripts" in caplog.text
        assert "NOT applied" in caplog.text


class TestSweep:
    def _seed_ledger(self, tmp_path, user_key: str, filenames: list[str]) -> None:
        ledger = tmp_path / ".curio" / "users" / user_key / "agents" / "ledger"
        ledger.mkdir(parents=True, exist_ok=True)
        for name in filenames:
            (ledger / name).write_text('{"kind": "reserve"}\n', encoding="utf-8")

    def test_no_declaration_moves_nothing(self, tmp_curio):
        self._seed_ledger(tmp_curio, "42", ["2020-01-01.jsonl"])
        result = retention.run_retention_sweep(today=date(2026, 8, 19))
        assert result == {"ledgerFilesArchived": 0}
        ledger = tmp_curio / ".curio" / "users" / "42" / "agents" / "ledger"
        assert (ledger / "2020-01-01.jsonl").is_file()
        assert not (ledger / "archive").exists()

    def test_declared_age_archives_only_past_age_files_byte_identically(self, tmp_curio):
        _write_declaration(tmp_curio, {"ledger": {"archiveAfterDays": 30}})
        self._seed_ledger(tmp_curio, "42", [
            "2026-01-01.jsonl",  # old — archived
            "2026-08-10.jsonl",  # 9 days old — kept
            "not-a-day.jsonl",   # non-day file — never touched
        ])
        ledger = tmp_curio / ".curio" / "users" / "42" / "agents" / "ledger"
        (ledger / ".lock").write_text("", encoding="utf-8")
        old_bytes = (ledger / "2026-01-01.jsonl").read_bytes()

        result = retention.run_retention_sweep(today=date(2026, 8, 19))

        assert result == {"ledgerFilesArchived": 1}
        assert not (ledger / "2026-01-01.jsonl").exists()
        assert (ledger / "archive" / "2026-01-01.jsonl").read_bytes() == old_bytes
        assert (ledger / "2026-08-10.jsonl").is_file()
        assert (ledger / "not-a-day.jsonl").is_file()
        assert (ledger / ".lock").is_file()

    def test_existing_archive_file_is_never_overwritten(self, tmp_curio, caplog):
        _write_declaration(tmp_curio, {"ledger": {"archiveAfterDays": 30}})
        self._seed_ledger(tmp_curio, "42", ["2026-01-01.jsonl"])
        ledger = tmp_curio / ".curio" / "users" / "42" / "agents" / "ledger"
        (ledger / "archive").mkdir()
        (ledger / "archive" / "2026-01-01.jsonl").write_text("prior archive", encoding="utf-8")

        with caplog.at_level("WARNING"):
            result = retention.run_retention_sweep(today=date(2026, 8, 19))

        assert result == {"ledgerFilesArchived": 0}
        assert (ledger / "archive" / "2026-01-01.jsonl").read_text(encoding="utf-8") == "prior archive"
        assert (ledger / "2026-01-01.jsonl").is_file()  # left in place
        assert "never overwritten" in caplog.text

    def test_missing_users_dir_is_a_noop(self, tmp_curio):
        _write_declaration(tmp_curio, {"ledger": {"archiveAfterDays": 1}})
        assert retention.run_retention_sweep() == {"ledgerFilesArchived": 0}


class TestPublicConfigRoute:
    def test_bootstrap_config_carries_the_declaration(self, client, tmp_curio):
        _write_declaration(tmp_curio, {"backups": "none"})
        cfg = client.get("/api/config/public").get_json()
        assert cfg["retention"] == {
            "backups": "none",
            "ledgerArchiveAfterDays": None,
            "closureGraceDays": None,
        }
