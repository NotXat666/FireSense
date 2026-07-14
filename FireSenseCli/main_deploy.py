# main_deploy.py — OPNsense deployment entry point
# Run: python main_deploy.py
# Prerequisites:
#   1. Trained model exists at checkpoints/dqn_final.weights.h5
#   2. Scaler exists at scaler.pkl
#   3. opnsense_config.py has correct API_KEY, API_SECRET, OPNSENSE_HOST
#   4. The alias 'rl_blocklist' exists in OPNsense → Firewall → Aliases
#   5. tighten_inbound / tighten_outbound rules created in OPNsense GUI
#      and their UUIDs set in opnsense_config.py RULE_UUIDS

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import config
import opnsense_config as ocfg
from opnsense_inference import run_inference_loop

_PLACEHOLDER_UUID = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"


def preflight_check():
    """Warn about missing prerequisites before starting."""
    issues  = []
    warnings = []

    # ── Artefacts ─────────────────────────────────────────────────────────────
    if not os.path.exists(ocfg.MODEL_PATH):
        issues.append(f"Model not found: {ocfg.MODEL_PATH}  — run main_train.py first")
    if not os.path.exists(ocfg.SCALER_PATH):
        issues.append(f"Scaler not found: {ocfg.SCALER_PATH} — run main_train.py first")

    # ── Credentials ───────────────────────────────────────────────────────────
    if ocfg.API_KEY == "your_api_key_here":
        issues.append("API_KEY not set in opnsense_config.py")
    if ocfg.API_SECRET == "your_api_secret_here":
        issues.append("API_SECRET not set in opnsense_config.py")

    # ── Live OPNsense connection ───────────────────────────────────────────────
    try:
        r = requests.get(
            ocfg.OPNSENSE_HOST + "/api/core/firmware/status",
            auth=(ocfg.API_KEY, ocfg.API_SECRET),
            verify=ocfg.VERIFY_SSL, timeout=6,
        )
        if r.status_code == 200:
            print(f"  [OK] OPNsense reachable at {ocfg.OPNSENSE_HOST}")
        else:
            issues.append(f"OPNsense API returned HTTP {r.status_code} — check credentials")
    except Exception as exc:
        issues.append(f"Cannot reach OPNsense at {ocfg.OPNSENSE_HOST}: {exc}")

    # ── rl_blocklist alias ────────────────────────────────────────────────────
    try:
        r = requests.get(
            ocfg.OPNSENSE_HOST + f"/api/firewall/alias_util/list/{ocfg.BLOCKLIST_ALIAS}",
            auth=(ocfg.API_KEY, ocfg.API_SECRET),
            verify=ocfg.VERIFY_SSL, timeout=6,
        )
        if r.status_code == 200:
            print(f"  [OK] Alias '{ocfg.BLOCKLIST_ALIAS}' exists")
        else:
            issues.append(
                f"Alias '{ocfg.BLOCKLIST_ALIAS}' not found (HTTP {r.status_code}) — "
                "create it in OPNsense GUI: Firewall → Aliases → Add (type: Host)"
            )
    except Exception:
        pass  # already flagged by connection check above

    # ── Tighten rule UUIDs ────────────────────────────────────────────────────
    for rule_name, uuid in ocfg.RULE_UUIDS.items():
        if uuid == _PLACEHOLDER_UUID:
            warnings.append(
                f"RULE_UUIDS['{rule_name}'] is still placeholder — "
                "action=tighten and action=rollback will silently fail. "
                "Create the rule in OPNsense GUI → Firewall → Rules, then paste its UUID into opnsense_config.py"
            )

    # ── Report ────────────────────────────────────────────────────────────────
    if issues:
        print("\n[Deploy] Pre-flight check FAILED:")
        for i in issues:
            print(f"  [FAIL] {i}")
        print()
        if any("Model" in i or "Scaler" in i or "Cannot reach" in i for i in issues):
            sys.exit(1)
        print("[Deploy] Proceeding with warnings.\n")

    if warnings:
        print("\n[Deploy] Warnings (non-fatal):")
        for w in warnings:
            print(f"  [WARN] {w}")
        print()

    if not issues and not warnings:
        print("[Deploy] Pre-flight check passed — all systems ready.\n")


def main():
    print("=" * 55)
    print("  FireRL — OPNsense Adaptive Firewall Deployment")
    print("=" * 55)
    print(f"  Host    : {ocfg.OPNSENSE_HOST}")
    print(f"  Model   : {ocfg.MODEL_PATH}")
    print(f"  Delta-T : {ocfg.DELTA_T}s")
    print("  Press Ctrl-C to stop.\n")

    preflight_check()

    run_inference_loop(
        model_path=ocfg.MODEL_PATH,
        scaler_path=ocfg.SCALER_PATH,
        delta_t=ocfg.DELTA_T,
        verbose=True,
    )


if __name__ == "__main__":
    main()
