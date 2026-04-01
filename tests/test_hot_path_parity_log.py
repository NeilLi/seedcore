from __future__ import annotations

from seedcore.ops.hot_path_parity_log import get_hot_path_parity_logger, reset_hot_path_parity_logger_for_tests


def test_promotion_window_eligible_when_full_window_meets_ratio(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDCORE_HOT_PATH_PARITY_LOG", str(tmp_path / "parity.jsonl"))
    monkeypatch.setenv("SEEDCORE_HOT_PATH_PROMOTION_WINDOW_N", "10")
    monkeypatch.setenv("SEEDCORE_HOT_PATH_PROMOTION_MIN_PARITY_RATIO", "0.999")
    reset_hot_path_parity_logger_for_tests()
    log = get_hot_path_parity_logger()
    for i in range(9):
        log.append({"parity_ok": True, "request_id": f"r{i}"})
    assert log.window_stats()["promotion_eligible"] is False
    log.append({"parity_ok": True, "request_id": "r9"})
    stats = log.window_stats()
    assert stats["window_events"] == 10
    assert stats["parity_ok_in_window"] == 10
    assert stats["promotion_eligible"] is True


def test_promotion_window_not_eligible_with_one_mismatch_in_ten(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDCORE_HOT_PATH_PARITY_LOG", str(tmp_path / "parity.jsonl"))
    monkeypatch.setenv("SEEDCORE_HOT_PATH_PROMOTION_WINDOW_N", "10")
    monkeypatch.setenv("SEEDCORE_HOT_PATH_PROMOTION_MIN_PARITY_RATIO", "0.999")
    reset_hot_path_parity_logger_for_tests()
    log = get_hot_path_parity_logger()
    for i in range(9):
        log.append({"parity_ok": True, "request_id": f"r{i}"})
    log.append({"parity_ok": False, "request_id": "bad"})
    stats = log.window_stats()
    assert stats["parity_ok_in_window"] == 9
    assert stats["promotion_eligible"] is False
