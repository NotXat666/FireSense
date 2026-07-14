"""Unit tests for OPNsenseActuator — action routing + error surfacing, no network.

All HTTP is stubbed by replacing `_api_call`, so these verify the local state
machine (blocklist, tighten flag) and the new error/apply_ok reporting that the
UI relies on to stop swallowing failures.
"""
import os
import pytest


@pytest.fixture
def actuator(tmp_path, monkeypatch):
    import opnsense_config as ocfg
    # keep the rule-change CSV inside the temp dir, not the repo's results/
    monkeypatch.setattr(ocfg, "LOG_PATH", str(tmp_path / "results" / "deployment.log"))
    ocfg.RULE_UUIDS = {"tighten_inbound": "uuid-in", "tighten_outbound": "uuid-out"}
    from opnsense_actuator import OPNsenseActuator
    return OPNsenseActuator()


def _ok(*_a, **_k):
    return {"status": "ok"}


def _done(*_a, **_k):
    # OPNsense alias_util add/delete actually returns {"status": "done"},
    # not "ok" — rollback/panic must treat it as success, not a failure.
    return {"status": "done"}


def _fail(*_a, **_k):
    return None


def test_block_ip_adds_to_blocklist(actuator, monkeypatch):
    monkeypatch.setattr(actuator, "_api_call", _ok)
    res = actuator.execute_action(1, suspicious_ip="1.2.3.4")
    assert "1.2.3.4" in actuator.blocklist
    assert res["applied"] is True
    assert res["errors"] == []


def test_block_ip_failure_is_surfaced(actuator, monkeypatch):
    monkeypatch.setattr(actuator, "_api_call", _fail)
    res = actuator.execute_action(1, suspicious_ip="9.9.9.9")
    assert "9.9.9.9" not in actuator.blocklist
    assert res["errors"]            # non-empty → UI will warn instead of staying silent


def test_tighten_sets_flag_and_reports_apply(actuator, monkeypatch):
    monkeypatch.setattr(actuator, "_api_call", _ok)
    res = actuator.execute_action(2)
    assert actuator.rules_tightened is True
    assert res["apply_ok"] is True
    assert res["errors"] == []


def test_tighten_apply_failure_flagged(actuator, monkeypatch):
    monkeypatch.setattr(actuator, "_api_call", _fail)
    res = actuator.execute_action(2)
    # every toggle failed and apply failed → both surfaced
    assert res["apply_ok"] is False
    assert res["errors"]


def test_rollback_removes_fraction(actuator, monkeypatch):
    monkeypatch.setattr(actuator, "_api_call", _ok)
    actuator.blocklist = [f"10.0.0.{i}" for i in range(10)]
    before = len(actuator.blocklist)
    actuator.execute_action(3)
    assert len(actuator.blocklist) < before   # partial unblock (1/ROLLBACK_FRACTION)


def test_panic_reset_clears_everything(actuator, monkeypatch):
    monkeypatch.setattr(actuator, "_api_call", _ok)
    actuator.blocklist = ["1.1.1.1", "2.2.2.2", "3.3.3.3"]
    actuator.rules_tightened = True
    res = actuator.panic_reset()
    assert actuator.blocklist == []
    assert actuator.rules_tightened is False
    assert res["action"] == "panic"
    assert res["apply_ok"] is True


def test_rollback_done_status_not_reported_as_failure(actuator, monkeypatch):
    # Real OPNsense returns status "done" on alias delete; unblocks must be
    # counted as changes, with no phantom "gagal" errors.
    monkeypatch.setattr(actuator, "_api_call", _done)
    actuator.blocklist = [f"10.0.0.{i}" for i in range(10)]
    res = actuator.execute_action(3)
    assert res["errors"] == []
    assert any("unblocked" in c for c in res["changes"])


def test_panic_done_status_not_reported_as_failure(actuator, monkeypatch):
    monkeypatch.setattr(actuator, "_api_call", _done)
    actuator.blocklist = ["1.1.1.1", "2.2.2.2"]
    res = actuator.panic_reset()
    assert actuator.blocklist == []
    assert res["errors"] == []
    assert any("unblocked" in c for c in res["changes"])
