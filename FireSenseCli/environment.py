# environment.py — Per-flow MDP environment (FireRL-equivalent design)
#
# Root causes fixed vs old version:
#   1. Per-flow state (not window aggregation) → dense, immediate reward signal
#   2. Action directly classifies CURRENT flow → no credit assignment delay
#   3. State includes rolling context so agent can adapt its policy over time

import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces
from collections import deque

import config
from state_engineering import extract_flow_features, encode_labels
from reward_function import compute_reward

MALICIOUS_LABELS = config.MALICIOUS_LABELS


class FirewallEnv(gym.Env):
    """
    Per-flow Markov Decision Process for Adaptive Dynamic Firewall.

    State  S  : 14 per-flow features  +  8 rolling/context features = 22 dims
    Actions A : {0=allow, 1=deny, 2=drop, 3=reset-both}  — Discrete(4)
    Reward R  : immediate per-flow feedback (Proposal Eq. 3.1, fixed)
    Episode   : STEPS_PER_EPISODE consecutive flow records
    """

    metadata = {"render.modes": []}

    # Rolling window for context statistics
    ROLLING_WINDOW = config.WINDOW_SIZE

    def __init__(self, X: np.ndarray, y: np.ndarray):
        """
        Parameters
        ----------
        X : scaled per-flow feature matrix  (N, N_FLOW_FEATURES)
        y : integer labels                  (N,)  0=allow 1=deny 2=drop 3=reset
        """
        super().__init__()

        self.X = X.astype(np.float32)
        self.y = y.astype(np.int32)
        self.n_samples = len(X)

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(config.STATE_DIM,), dtype=np.float32,
        )
        self.action_space = spaces.Discrete(config.NUM_ACTIONS)

        self.reset()

    # ── Context feature builder ───────────────────────────────────────────────

    def _build_obs(self) -> np.ndarray:
        """Concatenate current flow features with 8 rolling context features."""
        flow = self.X[self.ptr]           # (14,)

        # Context (8 features):
        # 1. rolling mean reward
        # 2. rolling std reward
        # 3. cumulative threat rate (attacks seen / steps)
        # 4. cumulative FP rate
        # 5. step progress in episode (0→1)
        # 6. last action taken (0-3, normalised)
        # 7. consecutive attack count (normalised)
        # 8. rule count proxy (normalised by 100)
        mean_r  = np.mean(self._reward_win)  if self._reward_win  else 0.0
        std_r   = np.std(self._reward_win)   if len(self._reward_win) > 1 else 0.0
        thr_r   = self._threat_count / max(self._step, 1)
        fp_r    = self._fp_count     / max(self._step, 1)
        prog    = self._step / config.STEPS_PER_EPISODE
        la_norm = self._last_action / (config.NUM_ACTIONS - 1)
        atk_seq = min(self._consec_attack, config.CONTEXT_MAX_CONSEC_ATK) / config.CONTEXT_MAX_CONSEC_ATK
        rule_n  = min(self._rule_count, config.CONTEXT_MAX_RULE_COUNT)  / config.CONTEXT_MAX_RULE_COUNT

        ctx = np.array(
            [mean_r, std_r, thr_r, fp_r, prog, la_norm, atk_seq, rule_n],
            dtype=np.float32,
        )
        return np.concatenate([flow, ctx])

    # ── Gym API ───────────────────────────────────────────────────────────────

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)

        # Sample a random contiguous episode from the dataset
        max_start = max(0, self.n_samples - config.STEPS_PER_EPISODE)
        self.ptr  = np.random.randint(0, max(max_start, 1))
        self._step = 0

        # Rolling reward window
        self._reward_win  = deque(maxlen=self.ROLLING_WINDOW)

        # Episode-level accumulators
        self.ep_tp = self.ep_fp = self.ep_tn = self.ep_fn = 0
        self.ep_latency = []
        self.ep_novel_detected = 0
        self.ep_novel_missed   = 0

        # Context state
        self._threat_count  = 0
        self._fp_count      = 0
        self._last_action   = 0
        self._consec_attack = 0
        self._rule_count    = 1

        return self._build_obs(), {}

    def step(self, action: int):
        assert self.action_space.contains(action)

        true_label   = int(self.y[self.ptr])
        is_malicious = true_label in MALICIOUS_LABELS

        # ── Immediate per-flow reward (Proposal Eq. 3.1, fixed) ──────────────
        reward, info = compute_reward(
            action=action,
            true_label=true_label,
            step=self._step,
            rule_count=self._rule_count,
        )

        # ── Novel threat tracking (high-port sources) ─────────────────────────
        src_port = float(self.X[self.ptr, 0])   # Source Port is feature 0 pre-scale
        novel    = (src_port > 1.5) and is_malicious   # >1.5 std above mean ≈ high port
        agent_blocks = (action in config.BLOCKING_ACTIONS)
        if novel:
            if agent_blocks:
                self.ep_novel_detected += 1
            else:
                self.ep_novel_missed += 1

        # ── Rule count update (deny/drop increases rule complexity) ───────────
        if action in {1, 2}:
            self._rule_count = min(self._rule_count + 1, config.ENV_MAX_RULE_COUNT)

        # ── Update episode accumulators ───────────────────────────────────────
        self.ep_tp += info["tp"]; self.ep_fp += info["fp"]
        self.ep_tn += info["tn"]; self.ep_fn += info["fn"]
        self.ep_latency.append(info["latency"])
        self._reward_win.append(reward)

        if is_malicious:
            self._threat_count += 1
            self._consec_attack += 1
        else:
            self._consec_attack = 0

        if info["fp"]:
            self._fp_count += 1

        self._last_action = action
        self.ptr          += 1
        self._step        += 1

        terminated = (self._step >= config.STEPS_PER_EPISODE) or (self.ptr >= self.n_samples)
        truncated  = False
        obs = self._build_obs() if not terminated else np.zeros(config.STATE_DIM, dtype=np.float32)

        return obs, reward, terminated, truncated, info

    def render(self, mode="human"):
        pass

    def close(self):
        pass
