"""Unit tests for DeploymentWorker pure helpers — no TensorFlow, no real loop.

We never call run() (that needs TF + a live OPNsense). Instead we construct the
worker and exercise the deterministic glue the deployment correctness leans on:
attack detection, connectivity de-dup, results-dir resolution, and the CSV
evidence writer the laporan references.
"""
import os
import types
import pytest
import pandas as pd


@pytest.fixture(scope="session")
def qapp():
    """QThread/QObject need a QCoreApplication to exist for signals to work."""
    from PyQt6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def worker(qapp):
    from worker import DeploymentWorker
    return DeploymentWorker(cfg_manager=None)


# ── _check_attack: ≥50 external packets in the window ─────────────────────────
def _collector_with(df):
    c = types.SimpleNamespace()
    c._last_raw_df = df
    return c


def test_check_attack_true_when_many_external(worker, monkeypatch):
    import opnsense_config as ocfg
    monkeypatch.setattr(ocfg, "OWN_IPS", {"10.0.2.4"}, raising=False)
    df = pd.DataFrame({"src_ip": ["8.8.8.8"] * 60})
    assert worker._check_attack(_collector_with(df)) is True


def test_check_attack_false_below_threshold(worker, monkeypatch):
    import opnsense_config as ocfg
    monkeypatch.setattr(ocfg, "OWN_IPS", {"10.0.2.4"}, raising=False)
    df = pd.DataFrame({"src_ip": ["8.8.8.8"] * 49})
    assert worker._check_attack(_collector_with(df)) is False


def test_check_attack_excludes_own_ips(worker, monkeypatch):
    import opnsense_config as ocfg
    # all 60 packets originate from an OWN ip → no external attack
    monkeypatch.setattr(ocfg, "OWN_IPS", {"8.8.8.8"}, raising=False)
    df = pd.DataFrame({"src_ip": ["8.8.8.8"] * 60})
    assert worker._check_attack(_collector_with(df)) is False


def test_check_attack_none_df(worker):
    assert worker._check_attack(_collector_with(None)) is False
    assert worker._check_attack(types.SimpleNamespace()) is False


# ── _set_connected: emit only on state change ────────────────────────────────
def test_set_connected_dedups(worker):
    seen = []
    worker.connected.connect(seen.append)
    worker._set_connected(True)
    worker._set_connected(True)     # duplicate — suppressed
    worker._set_connected(False)
    worker._set_connected(False)    # duplicate — suppressed
    worker._set_connected(True)
    assert seen == [True, False, True]


# ── _results_dir: dev mirrors backend results/ ───────────────────────────────
def test_results_dir_dev_mirrors_backend(worker, monkeypatch, tmp_path):
    import opnsense_config as ocfg
    log_path = str(tmp_path / "results" / "deployment.log")
    monkeypatch.setattr(ocfg, "LOG_PATH", log_path)
    assert worker._results_dir() == str(tmp_path / "results")


# ── _open_decision_log: writes header + data dictionary + snapshot dir ────────
def test_open_decision_log_writes_evidence_files(worker, monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "_results_dir", lambda: str(tmp_path))
    cfg = types.SimpleNamespace(NUM_ACTIONS=4, STATE_DIM=22, N_FLOW_FEATURES=14)

    w, f, snap = worker._open_decision_log(cfg)
    try:
        assert w is not None and f is not None
        # snapshot dir + the two thesis-evidence CSVs exist
        assert os.path.isdir(snap)
        decisions = tmp_path / "window_decisions.csv"
        dictionary = tmp_path / "window_decisions.dictionary.csv"
        assert decisions.exists() and dictionary.exists()
        # header has the 6 fixed cols + q0..q3 + s0..s21 = 32 columns
        header = decisions.read_text(encoding="utf-8").splitlines()[0]
        cols = header.split(",")
        assert cols[:6] == ["window_id", "timestamp", "action", "action_name",
                            "latency_ms", "blocklist_size"]
        assert "q3" in cols and "s21" in cols
        assert len(cols) == 6 + cfg.NUM_ACTIONS + cfg.STATE_DIM
    finally:
        if f:
            f.close()


def test_open_decision_log_survives_unwritable_dir(worker, monkeypatch):
    # a results dir that can't be created → returns (None, None, None), no raise
    monkeypatch.setattr(worker, "_results_dir", lambda: "/proc/nonexistent/nope")
    w, f, snap = worker._open_decision_log(
        types.SimpleNamespace(NUM_ACTIONS=4, STATE_DIM=22, N_FLOW_FEATURES=14))
    assert (w, f, snap) == (None, None, None)
