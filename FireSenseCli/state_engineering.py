# state_engineering.py — Feature engineering for per-flow training AND OPNsense deployment
#
# Training  : extract_flow_features(row)  called per individual flow record
# Deployment: compute_window_state(df)    called on a Δt window of OPNsense logs
#             → aggregates per-flow features to match what the DQN expects on average

import numpy as np
import pandas as pd
import config


# ── Per-flow feature extraction (used during TRAINING) ───────────────────────

FLOW_FEATURE_NAMES = [
    "Source Port",
    "Destination Port",
    "NAT Source Port",
    "NAT Destination Port",
    "Bytes",
    "Bytes Sent",
    "Bytes Received",
    "Packets",
    "Elapsed Time (sec)",
    "pkts_sent",
    "pkts_received",
    "bytes_per_packet",    # derived: Bytes / (Packets + 1e-9)
    "sent_recv_ratio",     # derived: Bytes Sent / (Bytes Received + 1e-8)
    "pkt_rate",            # derived: Packets / (Elapsed Time + 1e-9)
]


def extract_flow_features(row: pd.Series) -> np.ndarray:
    """
    Convert one flow record (pandas Series) into a 14-dim raw feature vector.
    This is the per-flow state input used during DQN training.

    Parameters
    ----------
    row : pd.Series with the Kaggle firewall dataset columns

    Returns
    -------
    np.ndarray, shape (N_FLOW_FEATURES,) — raw, un-normalised
    """
    def g(col, default=0.0):
        v = row.get(col, default)
        return float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else default

    src_port  = g("Source Port")
    dst_port  = g("Destination Port")
    nat_src   = g("NAT Source Port")
    nat_dst   = g("NAT Destination Port")
    bytes_    = g("Bytes")
    bytes_s   = g("Bytes Sent")
    bytes_r   = g("Bytes Received")
    packets   = g("Packets")
    elapsed   = g("Elapsed Time (sec)")
    pkts_s    = g("pkts_sent")
    pkts_r    = g("pkts_received")

    bpp        = bytes_  / (packets + 1e-9) # bytes_per_packet
    sr_ratio   = bytes_s / (bytes_r  + 1e-8) # sent_recv_ratio
    pkt_rate   = packets / (elapsed  + 1e-9) # pkt_rate

    return np.array(
        [src_port, dst_port, nat_src, nat_dst,
         bytes_, bytes_s, bytes_r,
         packets, elapsed, pkts_s, pkts_r,
         bpp, sr_ratio, pkt_rate],
        dtype=np.float32,
    )


def build_feature_matrix(df: pd.DataFrame) -> np.ndarray:
    """
    Vectorised version of extract_flow_features for the full DataFrame.
    Returns shape (N, 14).
    """
    out = np.zeros((len(df), config.N_FLOW_FEATURES), dtype=np.float32)
    for i, (_, row) in enumerate(df.iterrows()):
        out[i] = extract_flow_features(row)
    return out


# ── Label helpers ─────────────────────────────────────────────────────────────

ACTION_MAP = {"allow": 0, "deny": 1, "drop": 2, "reset-both": 3}


def encode_labels(series: pd.Series) -> np.ndarray:
    return series.str.strip().str.lower().map(ACTION_MAP).fillna(0).astype(np.int32).values


# ── Window-level aggregation — used ONLY for OPNsense deployment ──────────────

def compute_window_state(window_df: pd.DataFrame) -> np.ndarray:
    """
    Aggregate a window of OPNsense log entries into the same 14-dim feature
    space used during per-flow training (using mean values of the window).

    Called by opnsense_collector.py during deployment.
    The scaler fitted on per-flow training data is applied afterwards.
    """
    if len(window_df) == 0:
        return np.zeros(config.N_FLOW_FEATURES, dtype=np.float32)

    features = build_feature_matrix(window_df)
    return features.mean(axis=0)   # shape (14,) — mean per-flow state


def get_most_suspicious_ip(window_df: pd.DataFrame) -> str | None:
    """Return the source IP most associated with non-allow actions.

    Uses 'src_ip' column (real IP from OPNsense) when available.
    Falls back to Source Port only for training data that has no IP column.
    """
    if "Action" not in window_df.columns:
        return None
    mask = window_df["Action"].str.strip().str.lower() != "allow"
    if mask.sum() == 0:
        return None
    if "src_ip" in window_df.columns:
        candidates = window_df.loc[mask, "src_ip"]
        candidates = candidates[candidates.str.strip() != ""]
        if len(candidates) > 0:
            return candidates.value_counts().index[0]
    if "Source Port" not in window_df.columns:
        return None
    return str(int(window_df.loc[mask, "Source Port"].value_counts().index[0]))
