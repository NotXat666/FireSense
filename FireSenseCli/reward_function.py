# reward_function.py — Per-flow immediate reward (fixed signs + FN penalty)
#
# Root causes fixed vs old version:
#   1. W_FN_PENALTY: strong negative reward for missing attacks (was absent)
#   2. Signs: all weights are positive magnitudes; signs applied explicitly here
#   3. Immediate feedback: reward computed per individual flow, not per window

import config


def compute_reward(
    action: int,
    true_label: int,
    step: int = 0,
    rule_count: int = 1,
) -> tuple[float, dict]:
    """
    Per-flow multi-objective reward — Proposal Eq. 3.1 / FireRL Eq. 4

        R = +W1  if TP  (correctly block attack)
            -W2  if FP  (incorrectly block benign)
            -W_FN_PENALTY  if FN (miss an attack — strongest signal)
            +W_TN_BONUS    if TN (correctly allow benign)
            -W3 * latency  (decision overhead)
            +W4            if action matches ground-truth label exactly

    Parameters
    ----------
    action      : int  agent's chosen action (0=allow, 1=deny, 2=drop, 3=reset)
    true_label  : int  ground-truth label from dataset
    step        : int  current step index (for latency scaling)
    rule_count  : int  current active rule count (affects latency)

    Returns
    -------
    reward (float), info dict
    """
    is_malicious  = (true_label != config.BENIGN_LABEL)
    agent_blocks  = (action in config.BLOCKING_ACTIONS)

    # ── Classification outcomes ───────────────────────────────────────────────
    is_tp = is_malicious  and agent_blocks
    is_fp = (not is_malicious) and agent_blocks
    is_fn = is_malicious  and (not agent_blocks)
    is_tn = (not is_malicious) and (not agent_blocks)

    # ── Component 1: threat_blocked (TB) ──────────────────────────────────────
    tb = config.W1_THREAT_BLOCKED if is_tp else 0.0

    # ── Component 2: false_drop penalty (FD) ─────────────────────────────────
    fd = config.W2_FALSE_DROP if is_fp else 0.0

    # ── Component 3: missed attack penalty (FN) ──────────────────────────────
    # This is the key fix: strong negative signal so agent can't exploit "always allow"
    fn_pen = config.W_FN_PENALTY if is_fn else 0.0

    # ── Component 4: correct benign allow bonus (TN) ──────────────────────────
    tn_bonus = config.W_TN_BONUS if is_tn else 0.0

    # ── Component 5: latency penalty (LA) ────────────────────────────────────
    base_lat = config.ACTION_LATENCY.get(action, 0.2)
    rule_overhead = config.RULE_OVERHEAD_MULTIPLIER * min(rule_count, config.RULE_OVERHEAD_CAP)
    latency = config.W3_LATENCY_PENALTY * (base_lat + rule_overhead)

    # ── Component 6: policy compliance (PC) ──────────────────────────────────
    # Reward when agent exactly matches ground-truth policy label
    pc = config.W4_POLICY_COMPLIANCE if (action == true_label) else 0.0

    # ── Composite reward ─────────────────────────────────────────────────────
    reward = tb - fd - fn_pen + tn_bonus - latency + pc

    info = {
        "tp": int(is_tp), "fp": int(is_fp),
        "fn": int(is_fn), "tn": int(is_tn),
        "tb": tb, "fd": fd, "fn_pen": fn_pen,
        "tn_bonus": tn_bonus, "latency": base_lat,
        "pc": pc,
        "is_malicious": is_malicious,
        "agent_blocks": agent_blocks,
    }
    return float(reward), info
