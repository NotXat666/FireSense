# visualize.py — 5 performance plots for the DQN agent

import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import config

os.makedirs(config.RESULTS_DIR, exist_ok=True)

COLOR      = "#1f77b4"
GRID_STYLE = dict(linestyle="--", alpha=0.4, linewidth=0.8)
FIG_SIZE   = (8, 5)
X_TICKS    = list(range(0, config.MAX_EPISODES + 1, config.MAX_EPISODES // 5))
FONT_TITLE = dict(fontsize=13, fontweight="bold")
FONT_AXIS  = dict(fontsize=11)
TICK_FONT  = 10


def _smooth(values: list, window: int = 20) -> np.ndarray:
    arr = np.array(values, dtype=float)
    if len(arr) < window:
        return arr
    return np.convolve(arr, np.ones(window) / window, mode="same")


def _save(fig, filename: str):
    path = os.path.join(config.RESULTS_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [Visualize] → {path}")


# ── Plot 1: Cumulative Reward vs Episodes ─────────────────────────────────────

def plot_reward(history: dict):
    ep  = history["episode"]
    raw = history["cumulative_reward"]
    sm  = _smooth(raw)

    fig, ax = plt.subplots(figsize=FIG_SIZE)
    ax.plot(ep, raw, alpha=0.25, color=COLOR, linewidth=1)
    ax.plot(ep, sm,  color=COLOR, linewidth=2, label="DQN (smoothed)")
    ax.set_xlabel("Episode", **FONT_AXIS)
    ax.set_ylabel("Cumulative Reward", **FONT_AXIS)
    ax.set_title("Cumulative Reward vs Episodes", **FONT_TITLE)
    ax.set_xticks(X_TICKS)
    ax.tick_params(labelsize=TICK_FONT)
    ax.grid(**GRID_STYLE)
    ax.legend(fontsize=10)
    fig.tight_layout()
    _save(fig, "plot1_reward.png")


# ── Plot 2: Accuracy (%) vs Episodes ─────────────────────────────────────────

def plot_accuracy(history: dict):
    ep  = history["episode"]
    acc = _smooth(history["accuracy"])

    fig, ax = plt.subplots(figsize=FIG_SIZE)
    ax.plot(ep, acc, color=COLOR, linewidth=2, label="DQN")
    ax.set_xlabel("Number of Episodes", **FONT_AXIS)
    ax.set_ylabel("Accuracy (%)", **FONT_AXIS)
    ax.set_title("Accuracy vs Number of Episodes", **FONT_TITLE)
    ax.set_xticks(X_TICKS)
    ax.set_ylim(0, 105)
    ax.tick_params(labelsize=TICK_FONT)
    ax.grid(**GRID_STYLE)
    ax.legend(fontsize=10)
    fig.tight_layout()
    _save(fig, "plot2_accuracy.png")


# ── Plot 3: False Positive Rate (%) vs Episodes ───────────────────────────────

def plot_fpr(history: dict):
    ep  = history["episode"]
    fpr = _smooth(history["fpr"])

    fig, ax = plt.subplots(figsize=FIG_SIZE)
    ax.plot(ep, fpr, color=COLOR, linewidth=2, label="DQN")
    ax.set_xlabel("Number of Episodes", **FONT_AXIS)
    ax.set_ylabel("False Positive Rate (%)", **FONT_AXIS)
    ax.set_title("FPR vs Number of Episodes", **FONT_TITLE)
    ax.set_xticks(X_TICKS)
    ax.tick_params(labelsize=TICK_FONT)
    ax.grid(**GRID_STYLE)
    ax.legend(fontsize=10)
    fig.tight_layout()
    _save(fig, "plot3_fpr.png")


# ── Plot 4: Throughput vs Episodes ────────────────────────────────────────────

def plot_throughput(history: dict):
    ep   = np.array(history["episode"])
    tput = _smooth(history["throughput"])

    sample_idx = np.arange(0, len(ep), max(1, len(ep) // 20))
    ep_s   = ep[sample_idx]
    tput_s = tput[sample_idx]

    fig, ax1 = plt.subplots(figsize=FIG_SIZE)
    ax1.bar(ep_s, tput_s, width=35, alpha=0.35, color=COLOR, label="DQN (bar)")
    ax2 = ax1.twinx()
    ax2.plot(ep, tput, color=COLOR, linewidth=2, label="DQN (line)")
    ax1.set_xlabel("Number of Episodes", **FONT_AXIS)
    ax1.set_ylabel("Throughput (sampled)", **FONT_AXIS)
    ax2.set_ylabel("Throughput", **FONT_AXIS)
    ax1.set_title("Throughput vs Number of Episodes", **FONT_TITLE)
    ax1.set_xticks(X_TICKS)
    ax1.tick_params(labelsize=TICK_FONT)
    ax2.tick_params(labelsize=TICK_FONT)
    ax1.grid(**GRID_STYLE)
    lines1, l1 = ax1.get_legend_handles_labels()
    lines2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, l1 + l2, fontsize=10)
    fig.tight_layout()
    _save(fig, "plot4_throughput.png")


# ── Plot 5: Detection Metrics Bar Chart (final episode values) ────────────────

def plot_detection_bar(test_metrics: dict):
    """
    Grouped bar chart of Accuracy, Precision, Recall, F1 for the DQN agent
    (final test-set evaluation).
    """
    metrics_names = ["Accuracy", "Precision", "Recall", "F1-score"]
    values = [
        test_metrics["accuracy"],
        test_metrics["precision"],
        test_metrics["recall"],
        test_metrics["f1"],
    ]

    x   = np.arange(len(metrics_names))
    fig, ax = plt.subplots(figsize=FIG_SIZE)
    bars = ax.bar(x, values, width=0.5, color=COLOR, alpha=0.85, label="DQN Agent")

    # Value labels on bars
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.5,
                f"{val:.1f}%",
                ha="center", va="bottom", fontsize=10)

    ax.set_xticks(x)
    ax.set_xticklabels(metrics_names, fontsize=11)
    ax.set_ylabel("Score (%)", **FONT_AXIS)
    ax.set_ylim(0, 115)
    ax.set_title("Detection Metrics — DQN Agent (Test Set)", **FONT_TITLE)
    ax.tick_params(labelsize=TICK_FONT)
    ax.grid(axis="y", **GRID_STYLE)
    ax.legend(fontsize=10)
    fig.tight_layout()
    _save(fig, "plot5_detection_bar.png")


def generate_all_plots(history: dict, test_metrics: dict = None):
    print("\n[Visualize] Generating plots …")
    plot_reward(history)
    plot_accuracy(history)
    plot_fpr(history)
    plot_throughput(history)
    if test_metrics is not None:
        plot_detection_bar(test_metrics)
    print("[Visualize] All plots saved to:", config.RESULTS_DIR)
