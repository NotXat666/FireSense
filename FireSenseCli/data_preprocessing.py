import os
import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from imblearn.over_sampling import SMOTE
import warnings
warnings.filterwarnings("ignore")

import config
from state_engineering import build_feature_matrix, encode_labels, ACTION_MAP


def load_and_preprocess(dataset_path: str = None, verbose: bool = True):
    """
    Per-flow preprocessing pipeline.

    Key difference from old version: NO window aggregation.
    Each row in the dataset = one RL step. This gives the DQN dense,
    immediate reward feedback on every individual packet decision.

    Returns
    -------
    X_train, y_train : np.ndarray  (scaled per-flow features, int labels)
    X_test,  y_test  : np.ndarray
    raw_df_train     : pd.DataFrame  (raw rows, temporal order preserved)
    raw_df_test      : pd.DataFrame
    scaler           : fitted StandardScaler (saved to SCALER_PATH)
    """
    if dataset_path is None:
        dataset_path = config.DATASET_PATH

    # ── 1. Load ───────────────────────────────────────────────────────────────
    if verbose:
        print(f"[Preprocess] Loading {dataset_path} …")
    df = pd.read_csv(dataset_path)
    df.columns = [c.strip() for c in df.columns]
    if verbose:
        print(f"[Preprocess] Raw shape: {df.shape}")

    # ── 2. Clean ──────────────────────────────────────────────────────────────
    df.dropna(subset=["Action"], inplace=True)
    num_cols = df.select_dtypes(include=[np.number]).columns
    df[num_cols] = df[num_cols].fillna(df[num_cols].median())
    df.drop_duplicates(inplace=True)
    df["Action"] = df["Action"].str.strip().str.lower()
    df = df[df["Action"].isin(ACTION_MAP.keys())].reset_index(drop=True)
    if verbose:
        print(f"[Preprocess] After cleaning: {df.shape}")
        vc = df["Action"].value_counts()
        for label, cnt in vc.items():
            print(f"  {label}: {cnt} ({cnt/len(df)*100:.1f}%)")

    # ── 3. Temporal split (NO shuffle — preserves sequence for RL) ────────────
    split = int(len(df) * config.TRAIN_SPLIT)
    df_train = df.iloc[:split].reset_index(drop=True)
    df_test  = df.iloc[split:].reset_index(drop=True)
    if verbose:
        print(f"[Preprocess] Train: {len(df_train)} flows | Test: {len(df_test)} flows")

    # ── 4. Build per-flow feature matrices ────────────────────────────────────
    if verbose:
        print("[Preprocess] Extracting per-flow features …")
    X_train_raw = build_feature_matrix(df_train)
    X_test_raw  = build_feature_matrix(df_test)
    y_train     = encode_labels(df_train["Action"])
    y_test      = encode_labels(df_test["Action"])

    # ── 5. Fit scaler on training data only ───────────────────────────────────
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train_raw)
    X_test_scaled  = scaler.transform(X_test_raw)

    os.makedirs(os.path.dirname(config.SCALER_PATH), exist_ok=True)
    joblib.dump(scaler, config.SCALER_PATH)
    if verbose:
        print(f"[Preprocess] Scaler saved → {config.SCALER_PATH}")

    # ── 6. SMOTE on training set only ─────────────────────────────────────────
    if verbose:
        print("[Preprocess] Applying SMOTE …")
    sm = SMOTE(random_state=config.RANDOM_SEED)
    X_train, y_train = sm.fit_resample(X_train_scaled, y_train)
    if verbose:
        unique, counts = np.unique(y_train, return_counts=True)
        label_inv = {v: k for k, v in ACTION_MAP.items()}
        for u, c in zip(unique, counts):
            print(f"  After SMOTE '{label_inv[u]}': {c}")
        print(f"[Preprocess] Final → Train: {X_train.shape} | Test: {X_test_scaled.shape}")

    return X_train, y_train, X_test_scaled, y_test, df_train, df_test, scaler


if __name__ == "__main__":
    load_and_preprocess(verbose=True)
