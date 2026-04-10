from __future__ import annotations

from pathlib import Path


def test_init_full_db_direct_includes_transfer_and_rct_migrations() -> None:
    script = Path(__file__).resolve().parents[1] / "deploy" / "local" / "init-full-db-direct.sh"
    text = script.read_text()

    for migration in (
        "129_phase_a_trust_receipt_counter.sql",
        "130_transfer_approval_runtime.sql",
        "131_source_registration_settlement_statuses.sql",
        "132_pkg_rct_contract_phase1.sql",
    ):
        assert migration in text
