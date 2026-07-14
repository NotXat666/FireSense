"""
stages.py — Deployment preparation stages for FireSense.

Each stage validates one prerequisite for running the DQN firewall on the
user's own OPNsense. The user picks which stages to run; StageRunner executes
the selected ones in order on a background thread.

Stage keys:
  connection : reach + authenticate against the OPNsense API
  alias      : verify the blocklist alias exists
  rules      : verify tighten firewall rules are configured
  model      : load the DQN model + scaler and check dimensions
"""

import os
import sys
import time
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from PyQt6.QtCore import QThread, pyqtSignal


# Ordered metadata for display
STAGE_ORDER = ["connection", "alias", "rules", "model"]

STAGE_META = {
    "connection": ("Koneksi API OPNsense",
                   "Uji jangkauan & autentikasi ke REST API OPNsense"),
    "alias":      ("Verifikasi Alias Blocklist",
                   "Pastikan alias firewall untuk daftar blokir tersedia"),
    "rules":      ("Verifikasi Rule Tighten",
                   "Cek rule firewall untuk aksi 'tighten' (opsional)"),
    "model":      ("Muat Model DQN + Scaler",
                   "Muat bobot model FireRL dan scaler fitur"),
}

# status constants
OK, WARN, ERR = "ok", "warn", "error"


# ──────────────────────────────────────────────────────────────────────────────
# Individual stage checks — each returns (status, message)
# ──────────────────────────────────────────────────────────────────────────────

def _session(cfg):
    s = requests.Session()
    s.auth   = (cfg.get("api_key"), cfg.get("api_secret"))
    s.verify = bool(cfg.get("verify_ssl"))
    return s


def check_connection(cfg):
    host = (cfg.get("opnsense_host") or "").rstrip("/")
    if not host:
        return ERR, "Host OPNsense belum diisi."
    if not cfg.get("api_key") or not cfg.get("api_secret"):
        return ERR, "API Key / Secret belum diisi."
    try:
        s = _session(cfg)
        r = s.get(host + "/api/core/firmware/info", timeout=(5, 10))
        if r.status_code == 401:
            return ERR, "Autentikasi gagal (401), cek API Key/Secret."
        r.raise_for_status()
        data = r.json()
        # product_name = "OPNsense", product_version = firmware string e.g. "26.1.6_2"
        name = data.get("product_name") or "OPNsense"
        ver  = data.get("product_version") or ""
        label = f"{name} versi {ver}".strip() if ver else name
        return OK, f"Terhubung OK ({label})."
    except requests.exceptions.SSLError:
        return ERR, "Kesalahan SSL, nonaktifkan 'Verifikasi sertifikat SSL' atau pakai sertifikat valid."
    except requests.exceptions.ConnectTimeout:
        return ERR, f"Waktu habis: {host} tidak merespons."
    except requests.exceptions.ConnectionError:
        return ERR, f"Tidak bisa terhubung ke {host}."
    except Exception as e:
        return ERR, f"Gagal: {e}"


def check_alias(cfg):
    host  = (cfg.get("opnsense_host") or "").rstrip("/")
    alias = cfg.get("blocklist_alias") or "rl_blocklist"
    try:
        s = _session(cfg)
        r = s.get(f"{host}/api/firewall/alias_util/list/{alias}", timeout=(5, 10))
        if r.status_code == 404:
            return ERR, f"Alias '{alias}' tidak ditemukan, buat dulu di OPNsense."
        r.raise_for_status()
        data = r.json()
        rows = data.get("rows", data if isinstance(data, list) else [])
        n = len(rows) if isinstance(rows, list) else 0
        return OK, f"Alias '{alias}' OK ({n} entri saat ini)."
    except Exception as e:
        return ERR, f"Gagal cek alias '{alias}': {e}"


def check_rules(cfg):
    inb  = cfg.get("rule_tighten_inbound")
    outb = cfg.get("rule_tighten_outbound")
    if not inb and not outb:
        return WARN, "UUID rule tighten kosong, aksi 'tighten' akan dilewati."
    host = (cfg.get("opnsense_host") or "").rstrip("/")
    ok_rules, bad = [], []
    try:
        s = _session(cfg)
        for name, uuid in (("inbound", inb), ("outbound", outb)):
            if not uuid:
                continue
            r = s.get(f"{host}/api/firewall/filter/getRule/{uuid}", timeout=(5, 10))
            if r.status_code == 200 and r.json():
                ok_rules.append(name)
            else:
                bad.append(name)
    except Exception as e:
        return WARN, f"Tidak bisa memvalidasi rule ({e}); lanjut dengan asumsi valid."
    if bad:
        return WARN, f"Rule {', '.join(bad)} tidak tervalidasi; {', '.join(ok_rules) or 'tidak ada'} OK."
    return OK, f"Rule tighten OK ({', '.join(ok_rules)})."


def check_model(cfg):
    model_path  = cfg.model_path()
    scaler_path = cfg.scaler_path()
    if not os.path.exists(model_path):
        return ERR, f"Model tidak ditemukan: {os.path.basename(model_path)}"
    if not os.path.exists(scaler_path):
        return ERR, f"Scaler tidak ditemukan: {os.path.basename(scaler_path)}"
    try:
        import joblib
        joblib.load(scaler_path)          # verify scaler loads
        import config as cfgmod
        from dqn_agent import DQNAgent
        agent = DQNAgent(state_dim=cfgmod.STATE_DIM, num_actions=cfgmod.NUM_ACTIONS)
        agent.load(model_path)            # verify weights load into the network
        return OK, f"Model & scaler OK ({os.path.basename(model_path)})."
    except Exception as e:
        return ERR, f"Gagal memuat model: {e}"


STAGE_FUNCS = {
    "connection": check_connection,
    "alias":      check_alias,
    "rules":      check_rules,
    "model":      check_model,
}


# ──────────────────────────────────────────────────────────────────────────────
# StageRunner — runs selected stages sequentially on a worker thread
# ──────────────────────────────────────────────────────────────────────────────

class StageRunner(QThread):
    stage_started = pyqtSignal(str)              # key
    stage_result  = pyqtSignal(str, str, str)    # key, status, message
    all_done      = pyqtSignal(bool)             # True if no ERR among required

    def __init__(self, cfg, selected_keys, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.selected = [k for k in STAGE_ORDER if k in selected_keys]

    def run(self):
        any_error = False
        for key in self.selected:
            self.stage_started.emit(key)
            time.sleep(0.15)  # let the UI show the "running" state
            func = STAGE_FUNCS.get(key)
            try:
                status, msg = func(self.cfg)
            except Exception as e:
                status, msg = ERR, f"Exception: {e}"
            if status == ERR:
                any_error = True
            self.stage_result.emit(key, status, msg)
        self.all_done.emit(not any_error)
