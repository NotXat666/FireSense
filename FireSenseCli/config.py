# config.py — All hyperparameters and configuration

import os
import random
import numpy as np

# ── Reproducibility ───────────────────────────────────────────────────────────
RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_PATH   = os.path.join(BASE_DIR, "log2.csv")
CHECKPOINT_DIR = os.path.join(BASE_DIR, "checkpoints")
RESULTS_DIR    = os.path.join(BASE_DIR, "results")
SCALER_PATH    = os.path.join(BASE_DIR, "scaler.pkl")
MODEL_PATH     = os.path.join(CHECKPOINT_DIR, "dqn_final.weights.h5")

# ── Data ───────────────────────────────────────────────────────────────────────
TRAIN_SPLIT = 0.70
TEST_SPLIT  = 0.30

# Window size kept for OPNsense deployment only (not used during training)
WINDOW_SIZE            = 50
ATTACK_RATIO_THRESHOLD = 0.30

# ── Training ───────────────────────────────────────────────────────────────────
MAX_EPISODES      = 1000
STEPS_PER_EPISODE = 500   # per-flow steps per episode
BATCH_SIZE        = 64
LEARNING_RATE     = 0.001  # α
DISCOUNT_FACTOR   = 0.99   # γ

# ── Exploration — Epsilon-Greedy Exponential Decay (FireRL Eq. 7) ─────────────
EPSILON_MAX   = 1.0
EPSILON_MIN   = 0.01
EPSILON_DECAY = 0.001      # β — slowed for longer exploration

# ── Target Network — Soft Update (FireRL Eq. 6) ───────────────────────────────
TAU = 0.005

# ── Experience Replay ──────────────────────────────────────────────────────────
REPLAY_BUFFER_SIZE   = 100_000
PRIORITY_ALPHA       = 0.6   # prioritisation exponent (FireRL Eq. 5)
PRIORITY_BETA_START  = 0.4   # IS correction (annealed → 1.0)
PRIORITY_BETA_FRAMES = MAX_EPISODES * STEPS_PER_EPISODE

# ── Reward Weights ─────────────────────────────────────────────────────────────
# All weights are positive magnitudes; signs are applied in reward_function.py
W1_THREAT_BLOCKED    = 1.0   # reward for TP (block attack correctly)
W2_FALSE_DROP        = 1.5   # penalty for FP (block benign) — raised to force precision
W3_LATENCY_PENALTY   = 0.3   # penalty for decision overhead
W4_POLICY_COMPLIANCE = 1.0   # bonus when action matches ground-truth label — raised to reward precision
W_FN_PENALTY         = 2.0   # STRONG penalty for missing an attack (FN)
W_TN_BONUS           = 0.3   # increased bonus for correctly allowing benign

# ── L2 Regularisation (FireRL Eq. 3) ──────────────────────────────────────────
LAMBDA_REG = 0.001

# ── DQN Architecture ──────────────────────────────────────────────────────────
HIDDEN_LAYERS = [256, 256, 128]

# ── Action Space — deployment ACTION_NAMES: {0=maintain,1=block_ip,2=tighten,3=rollback}
NUM_ACTIONS = 4
# a0 = maintain  (pass/keep policy — benign, no change)
# a1 = block_ip  (block IP — new threat)
# a2 = tighten   (strict rules — sustained attack)
# a3 = rollback  (remove block — threat dissipated, UN-blocking)
BLOCKING_ACTIONS = {1, 2}   # rollback (3) is UN-blocking; updated for retrained model

# Per-action latency cost (normalised to [0, 1])
ACTION_LATENCY = {0: 0.1, 1: 0.3, 2: 0.2, 3: 0.4}

# ── State Dimension ────────────────────────────────────────────────────────────
# 14 per-flow features + 8 context features = 22
N_FLOW_FEATURES    = 14
N_CONTEXT_FEATURES = 8
STATE_DIM          = N_FLOW_FEATURES + N_CONTEXT_FEATURES   # 22

# ── ETDR Novelty Weight (FireRL Eq. 13) ───────────────────────────────────────
NOVELTY_LAMBDA = 1.5

# ── Latency equation constants (FireRL Eq. 9) ─────────────────────────────────
LATENCY_ALPHA = 0.4
LATENCY_BETA  = 0.3
LATENCY_GAMMA = 0.2
LATENCY_DELTA = 0.1

# ── Environment Constants ─────────────────────────────────────────────────────
MALICIOUS_LABELS        = {1, 2, 3}   # labels that represent attacks
BENIGN_LABEL            = 0           # label for benign/allow traffic
CONTEXT_MAX_CONSEC_ATK  = 20          # cap for consecutive attack counter
CONTEXT_MAX_RULE_COUNT  = 100         # cap for rule count normalisation
ENV_MAX_RULE_COUNT      = 200         # hard ceiling for rule count in env

# ── Throughput Formula Constants (FireRL Eq. 11) ──────────────────────────────
THROUGHPUT_BETA         = 0.1         # latency weight in throughput formula
THROUGHPUT_LAT_DIVISOR  = 10.0        # latency normalisation divisor

# ── Reward Overhead Constants ─────────────────────────────────────────────────
RULE_OVERHEAD_MULTIPLIER = 0.01       # per-rule latency overhead
RULE_OVERHEAD_CAP        = 100        # max rules counted for overhead

# ── Gradient Clipping ─────────────────────────────────────────────────────────
GRAD_CLIP_NORM = 10.0

# ── Rollback Policy ───────────────────────────────────────────────────────────
ROLLBACK_FRACTION = 5                 # remove 1/ROLLBACK_FRACTION of blocklist

# ── Logging / Checkpoints ─────────────────────────────────────────────────────
LOG_EVERY_EPISODES    = 10
SAVE_CHECKPOINT_EVERY = 100
