# evaluate.py — Offline evaluation metrics (Proposal Eqs. 2.1–2.7, FireRL Eqs. 9–13)

import numpy as np
import config


# ── Proposal Eq. 2.1 — Accuracy ──────────────────────────────────────────────

def accuracy(tp, tn, fp, fn) -> float:
    total = tp + tn + fp + fn
    return (tp + tn) / total * 100.0 if total > 0 else 0.0


# ── Proposal Eq. 2.2 — Precision ─────────────────────────────────────────────

def precision(tp, fp) -> float:
    return tp / (tp + fp) * 100.0 if (tp + fp) > 0 else 0.0


# ── Proposal Eq. 2.3 — Recall ────────────────────────────────────────────────

def recall(tp, fn) -> float:
    return tp / (tp + fn) * 100.0 if (tp + fn) > 0 else 0.0


# ── Proposal Eq. 2.4 — F1 Score ──────────────────────────────────────────────

def f1_score(tp, fp, fn) -> float:
    p = precision(tp, fp) / 100.0
    r = recall(tp, fn)    / 100.0
    return 2 * p * r / (p + r) * 100.0 if (p + r) > 0 else 0.0


# ── Proposal Eq. 2.5 — False Positive Rate ───────────────────────────────────

def false_positive_rate(fp, tn) -> float:
    return fp / (fp + tn) * 100.0 if (fp + tn) > 0 else 0.0


# ── Proposal Eq. 2.6 — Simulated Decision Latency (ms) ───────────────────────
# Corresponds to FireRL Equation 9

def compute_latency(latency_list: list) -> float:
    if not latency_list:
        return 0.0
    return float(np.mean(latency_list))


# ── Proposal Eq. 2.7 — Throughput ────────────────────────────────────────────
# Corresponds to FireRL Equation 11

def compute_throughput(packets: int, fpr_pct: float, latency_ms: float) -> float:
    fpr  = fpr_pct / 100.0
    beta = config.THROUGHPUT_BETA
    lat  = latency_ms / config.THROUGHPUT_LAT_DIVISOR
    return (packets * (1.0 - fpr)) / (1.0 + beta * lat)


# ── FireRL Eq. 13 — Enhanced Threat Detection Rate ───────────────────────────

def compute_etdr(tp, fn, novel_detected, novel_missed) -> float:
    lam   = config.NOVELTY_LAMBDA
    numer = tp + lam * novel_detected
    denom = tp + fn + lam * (novel_detected + novel_missed)
    return numer / denom * 100.0 if denom > 0 else 0.0


# ── Unified per-episode metrics ───────────────────────────────────────────────

def compute_episode_metrics(tp, tn, fp, fn,
                             latency_list: list,
                             novel_detected: int = 0,
                             novel_missed: int = 0) -> dict:
    acc  = accuracy(tp, tn, fp, fn)
    prec = precision(tp, fp)
    rec  = recall(tp, fn)
    f1   = f1_score(tp, fp, fn)
    fpr  = false_positive_rate(fp, tn)
    lat  = compute_latency(latency_list)
    pkts = tp + tn + fp + fn
    tput = compute_throughput(pkts, fpr, lat)
    etdr = compute_etdr(tp, fn, novel_detected, novel_missed)

    return {
        "accuracy":   acc,
        "precision":  prec,
        "recall":     rec,
        "f1":         f1,
        "fpr":        fpr,
        "latency":    lat,
        "throughput": tput,
        "etdr":       etdr,
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
    }


# ── Full test-set evaluation ──────────────────────────────────────────────────

def evaluate_on_test(agent, X_test: np.ndarray, y_test: np.ndarray,
                     verbose: bool = True) -> dict:
    """
    Run the trained agent greedily on the test set and return all metrics.
    """
    from environment import FirewallEnv

    env   = FirewallEnv(X_test, y_test)
    state, _ = env.reset()
    done  = False
    total_reward = 0.0

    while not done:
        action = agent.predict(state)
        state, reward, done, _trunc, _ = env.step(action)
        total_reward += reward

    metrics = compute_episode_metrics(
        tp=env.ep_tp, tn=env.ep_tn, fp=env.ep_fp, fn=env.ep_fn,
        latency_list=env.ep_latency,
        novel_detected=env.ep_novel_detected,
        novel_missed=env.ep_novel_missed,
    )
    metrics["total_reward"] = total_reward

    if verbose:
        print("\n[Evaluation] Test-set Results (DQN Agent):")
        print(f"  Accuracy   : {metrics['accuracy']:.2f}%")
        print(f"  Precision  : {metrics['precision']:.2f}%")
        print(f"  Recall     : {metrics['recall']:.2f}%")
        print(f"  F1-score   : {metrics['f1']:.2f}%")
        print(f"  FPR        : {metrics['fpr']:.2f}%")
        print(f"  Latency    : {metrics['latency']:.4f} ms")
        print(f"  Throughput : {metrics['throughput']:.2f}")
        print(f"  ETDR       : {metrics['etdr']:.2f}%")
        print(f"  Total Reward: {total_reward:.2f}")

    return metrics
