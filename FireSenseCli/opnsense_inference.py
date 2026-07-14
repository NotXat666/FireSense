# opnsense_inference.py — Real-time inference loop for OPNsense deployment

import csv
import os
import time
import logging
import signal
import json
import numpy as np
import pandas as pd

import opnsense_config as ocfg
from opnsense_collector import OPNsenseCollector
from opnsense_actuator  import OPNsenseActuator
from dqn_agent import DQNAgent
import config

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(ocfg.LOG_PATH), exist_ok=True)
logging.basicConfig(
    filename=ocfg.LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Console handler
console = logging.StreamHandler()
console.setLevel(logging.INFO)
log.addHandler(console)

# Action names for display
ACTION_NAMES = {0: "maintain", 1: "block_ip", 2: "tighten", 3: "rollback"}

# Graceful shutdown flag
_running = True

def _signal_handler(sig, frame):
    global _running
    log.info("[Inference] Shutdown signal received. Stopping after current window …")
    _running = False

signal.signal(signal.SIGINT,  _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def run_inference_loop(
    model_path:  str = None,
    scaler_path: str = None,
    delta_t:     int = None,
    verbose:     bool = True,
):
    """
    Main OPNsense inference loop.

    Algorithm:
      while True:
        state = collector.collect_window()
        action = agent.predict(state)
        result = actuator.execute_action(action)
        measure decision_latency
        sleep(Δt)

    Metrics tracked: action distribution, decision latency per window.
    Stop with Ctrl-C or SIGTERM.
    """
    model_path  = model_path  or ocfg.MODEL_PATH
    scaler_path = scaler_path or ocfg.SCALER_PATH
    delta_t     = delta_t     or ocfg.DELTA_T

    # ── Load agent ────────────────────────────────────────────────────────────
    log.info("[Inference] Loading DQN agent …")
    agent = DQNAgent(state_dim=config.STATE_DIM, num_actions=config.NUM_ACTIONS)
    agent.load(model_path)
    log.info(f"[Inference] Model loaded from {model_path}")

    # ── Initialise collector and actuator ─────────────────────────────────────
    collector = OPNsenseCollector(scaler_path=scaler_path)
    actuator  = OPNsenseActuator()

    # ── Metrics accumulator ───────────────────────────────────────────────────
    stats = {
        "windows_processed": 0,
        "action_counts":     {0: 0, 1: 0, 2: 0, 3: 0},
        "latencies_ms":      [],
    }

    # ── Persistent decision log ───────────────────────────────────────────────
    results_dir       = os.path.dirname(ocfg.LOG_PATH)
    decisions_path    = os.path.join(results_dir, "window_decisions.csv")
    snapshot_dir      = os.path.join(results_dir, "traffic_snapshot")
    os.makedirs(snapshot_dir, exist_ok=True)

    _dec_header_written = os.path.exists(decisions_path)
    _decisions_file = open(decisions_path, "a", newline="")
    _decisions_writer = csv.writer(_decisions_file)
    if not _dec_header_written:
        _decisions_writer.writerow(
            ["window_id", "timestamp", "action", "action_name",
             "latency_ms", "blocklist_size"]
            + [f"q{i}" for i in range(config.NUM_ACTIONS)]
            + [f"s{i}" for i in range(config.STATE_DIM)]
        )

    log.info(f"[Inference] Starting loop — Δt = {delta_t}s")
    window_idx = 0
    _consec_safe_windows = 0   # consecutive windows with no attack (for rollback guard)
    ROLLBACK_SAFE_MIN    = 5   # windows of calm required before rollback is permitted

    while _running:
        t_window_end = time.time()

        # ── Collect state ─────────────────────────────────────────────────────
        state = collector.collect_window()

        # ── Detect attack early — needed for rollback guard below ─────────────
        raw_df = getattr(collector, "_last_raw_df", None)
        is_attack_hint = False
        if raw_df is not None and len(raw_df) > 0:
            OWN_IPS = {"10.0.2.4", "127.0.0.1", "::1", ""}
            ext = raw_df[~raw_df.get("src_ip", pd.Series(dtype=str)).isin(OWN_IPS)] if "src_ip" in raw_df.columns else pd.DataFrame()
            if len(ext) >= 50:
                is_attack_hint = True
        if is_attack_hint:
            _consec_safe_windows = 0
        else:
            _consec_safe_windows += 1

        # ── DQN inference (greedy, Equation 7 with ε=0) ──────────────────────
        action, q_values = agent.predict_with_qvalues(state)

        # ── Rollback guard: prevent rollback unless safe to do so ─────────────
        # Root cause: original model assigns high Q(rollback) during heavy attacks
        # (semantic mismatch: training action3=reset-both vs deployment action3=rollback).
        # Guard conditions — all must hold before rollback is permitted:
        #   1. Blocklist is non-empty (there is something to unblock)
        #   2. No active attack traffic in this window
        #   3. At least ROLLBACK_SAFE_MIN consecutive calm windows observed
        if action == 3:
            safe_to_rollback = (
                actuator.blocklist_size > 0
                and not is_attack_hint
                and _consec_safe_windows >= ROLLBACK_SAFE_MIN
            )
            if not safe_to_rollback:
                if is_attack_hint:
                    # Under attack, action 3 reflects the model's training semantics
                    # (reset-both = BLOCKING), not deployment rollback. Honor that
                    # intent: take the best BLOCKING action (block_ip/tighten) rather
                    # than idling on maintain.
                    action = max(config.BLOCKING_ACTIONS, key=lambda a: q_values[a])
                    log.info(
                        f"[RollbackGuard] Rollback during attack → {ACTION_NAMES[action]} "
                        f"(best blocking; q={ {a: round(float(q_values[a]), 2) for a in sorted(config.BLOCKING_ACTIONS)} })"
                    )
                else:
                    log.info(
                        f"[RollbackGuard] Suppressed rollback "
                        f"(blk={actuator.blocklist_size}, atk={is_attack_hint}, "
                        f"safe_windows={_consec_safe_windows}/{ROLLBACK_SAFE_MIN}) → maintain"
                    )
                    action = 0

        # Determine suspicious IP for block_ip action
        # Collector stores the most suspicious IP from per-IP aggregation
        suspicious_ip = None
        if action == 1:
            suspicious_ip = getattr(collector, "suspicious_ip", None)

        # ── Execute action ────────────────────────────────────────────────────
        result = actuator.execute_action(action, suspicious_ip=suspicious_ip)

        # ── Measure decision latency (Proposal Eq. 2.6) ──────────────────────
        t_effective    = result.get("t_effective", time.time())
        decision_lat_s = t_effective - t_window_end
        decision_lat_ms = decision_lat_s * 1000.0

        # ── Update collector context ──────────────────────────────────────────
        collector.update_context(
            action,
            blocked=(action in config.BLOCKING_ACTIONS),
            is_attack_hint=is_attack_hint,
            blocklist_size=actuator.blocklist_size,
        )

        # ── Persist window decision log ───────────────────────────────────────
        import datetime as _dt
        ts_now = _dt.datetime.now().isoformat(timespec="seconds")
        _decisions_writer.writerow(
            [window_idx, ts_now, action, ACTION_NAMES[action],
             f"{decision_lat_ms:.3f}", actuator.blocklist_size]
            + q_values
            + state.tolist()
        )
        _decisions_file.flush()

        # ── Persist raw traffic snapshot ──────────────────────────────────────
        raw_df = getattr(collector, "_last_raw_df", None)
        if raw_df is not None and len(raw_df) > 0:
            snap_path = os.path.join(snapshot_dir, f"window_{window_idx:06d}.csv")
            raw_df.to_csv(snap_path, index=False)

        # ── Accumulate stats ──────────────────────────────────────────────────
        stats["windows_processed"] += 1
        stats["action_counts"][action] += 1
        stats["latencies_ms"].append(decision_lat_ms)

        # ── Log ───────────────────────────────────────────────────────────────
        log_line = (
            f"Window {window_idx:5d} | "
            f"Action: {ACTION_NAMES[action]:<10} | "
            f"Latency: {decision_lat_ms:.1f}ms | "
            f"Blocklist: {actuator.blocklist_size}"
        )
        if verbose:
            print(log_line)
        log.info(log_line)

        window_idx += 1

        # Sleep until next window
        elapsed = time.time() - t_window_end
        sleep_s = max(0.0, delta_t - elapsed)
        time.sleep(sleep_s)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    _decisions_file.close()

    # ── Summary on exit ───────────────────────────────────────────────────────
    _print_summary(stats)


def _print_summary(stats: dict):
    lats = stats["latencies_ms"]
    print("\n" + "=" * 50)
    print("  FireRL OPNsense Deployment — Session Summary")
    print("=" * 50)
    print(f"  Windows processed : {stats['windows_processed']}")
    for a, name in ACTION_NAMES.items():
        print(f"  Action '{name}' count : {stats['action_counts'][a]}")
    if lats:
        print(f"  Avg decision latency : {np.mean(lats):.2f} ms")
        print(f"  Max decision latency : {np.max(lats):.2f} ms")
    print("=" * 50)

    # Save to JSON
    summary_path = os.path.join(os.path.dirname(ocfg.LOG_PATH), "deployment_summary.json")
    with open(summary_path, "w") as f:
        json.dump({
            "windows_processed": stats["windows_processed"],
            "action_counts":     stats["action_counts"],
            "avg_latency_ms":    float(np.mean(lats)) if lats else 0.0,
            "max_latency_ms":    float(np.max(lats))  if lats else 0.0,
        }, f, indent=2)
    print(f"  Summary saved → {summary_path}")


if __name__ == "__main__":
    run_inference_loop()
