# main_train.py — Offline training entry point
# Run: python main_train.py

import os
import sys
import json
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data_preprocessing import load_and_preprocess
from train import train
from evaluate import evaluate_on_test
from visualize import generate_all_plots


def print_summary_table(test_metrics: dict):
    print("\n" + "=" * 55)
    print("  Adaptive Firewall DQN — Final Results (Test Set)")
    print("=" * 55)
    rows = [
        ("Accuracy (%)",                  f"{test_metrics['accuracy']:.2f}"),
        ("Precision (%)",                 f"{test_metrics['precision']:.2f}"),
        ("Recall (%)",                    f"{test_metrics['recall']:.2f}"),
        ("F1-score (%)",                  f"{test_metrics['f1']:.2f}"),
        ("False Positive Rate (%)",       f"{test_metrics['fpr']:.2f}"),
        ("Latency (ms)",                  f"{test_metrics['latency']:.4f}"),
        ("Throughput",                    f"{test_metrics['throughput']:.2f}"),
        ("Enhanced Threat Detection (%)", f"{test_metrics['etdr']:.2f}"),
        ("TP",                            str(test_metrics['tp'])),
        ("TN",                            str(test_metrics['tn'])),
        ("FP",                            str(test_metrics['fp'])),
        ("FN",                            str(test_metrics['fn'])),
    ]
    for name, val in rows:
        print(f"  {name:<35} {val:>10}")
    print("=" * 55 + "\n")


def main():
    os.makedirs(config.CHECKPOINT_DIR, exist_ok=True)
    os.makedirs(config.RESULTS_DIR,    exist_ok=True)

    # ── 1. Per-flow preprocessing ─────────────────────────────────────────────
    (X_train, y_train,
     X_test,  y_test,
     df_train, df_test,
     scaler) = load_and_preprocess(verbose=True)

    # ── 2–4. Train DQN agent ───────────────────────────────────────────────────
    agent, history = train(X_train, y_train, verbose=True)

    # ── 5. Evaluate on test set ────────────────────────────────────────────────
    test_metrics = evaluate_on_test(agent, X_test, y_test, verbose=True)
    # (df_train, df_test, scaler retained for OPNsense deployment)

    # ── 6. Generate all 5 plots ────────────────────────────────────────────────
    generate_all_plots(history, test_metrics)

    # ── 7. Print summary ──────────────────────────────────────────────────────
    print_summary_table(test_metrics)

    # Save history to JSON
    hist_path = os.path.join(config.RESULTS_DIR, "training_history.json")
    serialisable = {k: [float(v) for v in vals] for k, vals in history.items()}
    with open(hist_path, "w") as f:
        json.dump(serialisable, f, indent=2)
    print(f"[Main] Training history → {hist_path}")


if __name__ == "__main__":
    main()
