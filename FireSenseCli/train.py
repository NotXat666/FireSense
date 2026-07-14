# train.py — Training loop (Algorithm 1, FireRL paper — adapted for window MDP)

import os
import time
import logging
import numpy as np

import config
from environment import FirewallEnv
from dqn_agent import DQNAgent
from evaluate import compute_episode_metrics

os.makedirs(config.CHECKPOINT_DIR, exist_ok=True)
os.makedirs(config.RESULTS_DIR, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(config.RESULTS_DIR, "training.log"),
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def train(X_train: np.ndarray, y_train: np.ndarray,
          verbose: bool = True) -> tuple:
    """
    FireRL Algorithm 1 (adapted):

    Input : window-aggregated traffic T, DQN agent Q, reward R, ε, E
    Output: trained agent + training history dict

    Returns
    -------
    agent   : DQNAgent
    history : dict[str, list]  — per-episode metric lists
    """
    env   = FirewallEnv(X_train, y_train)
    agent = DQNAgent(state_dim=config.STATE_DIM, num_actions=config.NUM_ACTIONS)

    history = {
        "episode":          [],
        "cumulative_reward":[],
        "accuracy":         [],
        "precision":        [],
        "recall":           [],
        "f1":               [],
        "latency":          [],
        "throughput":       [],
        "fpr":              [],
        "etdr":             [],
        "epsilon":          [],
        "loss":             [],
    }

    if verbose:
        print(f"\n{'='*65}")
        print(f"  FireRL — Adaptive Dynamic Firewall Training")
        print(f"  Episodes: {config.MAX_EPISODES}  |  Steps/ep: {config.STEPS_PER_EPISODE}")
        print(f"  State dim: {config.STATE_DIM}  |  Actions: {config.NUM_ACTIONS}")
        print(f"{'='*65}\n")

    t0 = time.time()

    for episode in range(1, config.MAX_EPISODES + 1):
        # Initialize state S0
        state, _ = env.reset()
        done  = False
        cumulative_reward = 0.0
        losses = []

        # ── Episode loop ──────────────────────────────────────────────────────
        while not done:
            # Equation 7: ε-greedy
            action = agent.select_action(state)

            # Execute action
            next_state, reward, done, _truncated, info = env.step(action)

            # Store in replay buffer D
            agent.store_transition(state, action, reward, next_state, float(done))

            # Sample mini-batch & update (Equations 2, 3, 5)
            loss = agent.train_step()
            if loss is not None:
                losses.append(loss)

            state = next_state
            cumulative_reward += reward

        # Soft update θ⁻ (Equation 6) — after each episode
        agent.soft_update_target()

        # ── Compute episode metrics ───────────────────────────────────────────
        metrics = compute_episode_metrics(
            tp=env.ep_tp, tn=env.ep_tn, fp=env.ep_fp, fn=env.ep_fn,
            latency_list=env.ep_latency,
            novel_detected=env.ep_novel_detected,
            novel_missed=env.ep_novel_missed,
        )
        mean_loss = float(np.mean(losses)) if losses else 0.0

        history["episode"].append(episode)
        history["cumulative_reward"].append(cumulative_reward)
        history["accuracy"].append(metrics["accuracy"])
        history["precision"].append(metrics["precision"])
        history["recall"].append(metrics["recall"])
        history["f1"].append(metrics["f1"])
        history["latency"].append(metrics["latency"])
        history["throughput"].append(metrics["throughput"])
        history["fpr"].append(metrics["fpr"])
        history["etdr"].append(metrics["etdr"])
        history["epsilon"].append(agent.epsilon)
        history["loss"].append(mean_loss)

        # ── Logging / printing ────────────────────────────────────────────────
        log_msg = (
            f"Ep {episode:4d} | R={cumulative_reward:+7.2f} | "
            f"Acc={metrics['accuracy']:5.1f}% | F1={metrics['f1']:5.1f}% | "
            f"FPR={metrics['fpr']:5.2f}% | ETDR={metrics['etdr']:5.1f}% | "
            f"Lat={metrics['latency']:.3f}ms | ε={agent.epsilon:.4f} | "
            f"Loss={mean_loss:.4f}"
        )
        log.info(log_msg)

        if verbose and (episode % config.LOG_EVERY_EPISODES == 0 or episode == 1):
            elapsed = time.time() - t0
            print(f"{log_msg} [{elapsed:.0f}s]")

        # ── Checkpoint ────────────────────────────────────────────────────────
        if episode % config.SAVE_CHECKPOINT_EVERY == 0:
            ckpt = os.path.join(config.CHECKPOINT_DIR, f"dqn_ep{episode}.weights.h5")
            agent.save(ckpt)
            if verbose:
                print(f"  [Checkpoint] → {ckpt}")

    # Final model save
    agent.save(config.MODEL_PATH)
    if verbose:
        print(f"\n[Train] Finished in {time.time()-t0:.1f}s")
        print(f"[Train] Final model → {config.MODEL_PATH}")

    return agent, history
