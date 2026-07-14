# opnsense_config.example.py — TEMPLATE konfigurasi OPNsense API
# ---------------------------------------------------------------------------
# Salin file ini menjadi `opnsense_config.py` lalu isi nilai kredensial-mu:
#     cp opnsense_config.example.py opnsense_config.py
# `opnsense_config.py` di-.gitignore agar kredensial asli TIDAK ikut ter-commit.
# ---------------------------------------------------------------------------

# ── Connection ────────────────────────────────────────────────────────────────
OPNSENSE_HOST = "https://192.168.1.1"      # alamat OPNsense (gunakan https)
API_KEY       = "your_api_key_here"        # OPNsense → System → Access → Users → API Keys
API_SECRET    = "your_api_secret_here"
VERIFY_SSL    = False                      # Set True in production with valid cert

# ── Timing ────────────────────────────────────────────────────────────────────
DELTA_T         = 30    # seconds per inference window (dikunci 30 — window pelatihan model)
LOG_FETCH_LIMIT = 1500  # max log entries to pull per Δt (rollback needs ~1497 pkts visible)

# ── Self-traffic IPs — ignored when picking the suspicious source ─────────────
# WAN IP of this OPNsense + loopbacks. Overridable at runtime (FireSense app).
OWN_IPS = {"10.0.0.1", "127.0.0.1", "::1", ""}

# ── API Endpoints ─────────────────────────────────────────────────────────────
ENDPOINTS = {
    "firewall_log":      "/api/diagnostics/firewall/log",
    "interface_stats":   "/api/diagnostics/interface/getInterfaceStatistics",
    "alias_add":         "/api/firewall/alias_util/add/{alias}",
    "alias_delete":      "/api/firewall/alias_util/delete/{alias}",
    "alias_list":        "/api/firewall/alias_util/list/{alias}",
    "filter_apply":      "/api/firewall/filter/apply",
    "rule_toggle":       "/api/firewall/filter/toggleRule/{uuid}",
}

# ── Dynamic blocklist alias (must be created in OPNsense GUI first) ───────────
BLOCKLIST_ALIAS = "rl_blocklist"

# ── Pre-configured rule UUIDs (created via API, start disabled — DQN toggles)
# Isi dengan UUID rule tighten kamu (Firewall → Rules). Biarkan kosong jika belum ada.
RULE_UUIDS = {
    "tighten_inbound":  "",
    "tighten_outbound": "",
}

# ── Paths to saved model artefacts ────────────────────────────────────────────
import os
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Original model — good baseline + attack behavior; rollback guarded in opnsense_inference.py
MODEL_PATH  = os.path.join(_BASE, "checkpoints", "dqn_final.weights.h5")
SCALER_PATH = os.path.join(_BASE, "scaler.pkl")
LOG_PATH    = os.path.join(_BASE, "results",     "deployment.log")
