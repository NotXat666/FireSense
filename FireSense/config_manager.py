"""
config_manager.py — User-configurable settings for FireSense.

Stores OPNsense connection + deployment settings in a per-user JSON file so the
app can be distributed and each user points it at their own OPNsense instance.

Location:
  Windows : %APPDATA%\\FireSense\\config.json
  Linux   : ~/.config/firesense/config.json
"""

import os
import sys
import json
import copy


# ── Where bundled resources live (model, scaler) — handles PyInstaller .exe ───
def resource_base() -> str:
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def _default_model_path() -> str:
    return os.path.join(resource_base(), "checkpoints", "dqn_final.weights.h5")


def _default_scaler_path() -> str:
    return os.path.join(resource_base(), "scaler.pkl")


# ── Default settings — blank credentials so each user fills their own ─────────
DEFAULTS = {
    # Connection
    "opnsense_host":  "https://127.0.0.1:8443",
    "api_key":        "",
    "api_secret":     "",
    "verify_ssl":     False,

    # Environment
    "wan_ip":         "10.0.2.4",     # OPNsense WAN IP — ignored as self-traffic
    "wan_if":         "wan",          # logical OPNsense interface name (for rules)
    "wan_phys_if":    "em0",          # physical NIC as it appears in firewall logs
    "blocklist_alias": "rl_blocklist",
    "rule_tighten_inbound":  "",       # firewall rule UUID (optional)
    "rule_tighten_outbound": "",       # firewall rule UUID (optional)

    # Timing
    "delta_t":         30,             # seconds per inference window
    "log_fetch_limit": 1500,
    "latency_warn_ms": 1200,           # dashboard turns latency red above this
    "unblock_ttl_s":   0,              # auto-unblock IP setelah N detik aman (0 = mati/manual)

    # Model artefacts (default to bundled files; user may override)
    "model_path":  "",                 # blank → use bundled default
    "scaler_path": "",                 # blank → use bundled default

    # Which deployment stages to run (checked by default)
    "stages_enabled": {
        "connection": True,
        "alias":      True,
        "rules":      True,
        "model":      True,
    },
}


def config_dir() -> str:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "FireSense")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        d = os.path.join(base, "firesense")
    os.makedirs(d, exist_ok=True)
    return d


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


class ConfigManager:
    """Load / save / access user settings with sane fallbacks."""

    def __init__(self):
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    # ── persistence ──────────────────────────────────────────────────────────
    def load(self):
        p = config_path()
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # merge (keep defaults for any missing key)
                for k, v in saved.items():
                    if k == "stages_enabled" and isinstance(v, dict):
                        self.data["stages_enabled"].update(v)
                    else:
                        self.data[k] = v
            except Exception:
                pass  # corrupt file → keep defaults
        return self.data

    def save(self):
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    # ── access ───────────────────────────────────────────────────────────────
    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value):
        self.data[key] = value

    # Resolved paths: explicit user path > bundled file > FireSenseCli default
    def model_path(self) -> str:
        if self.data.get("model_path"):
            return self.data["model_path"]
        bundled = _default_model_path()
        if os.path.exists(bundled):
            return bundled
        try:
            import opnsense_config as ocfg
            return ocfg.MODEL_PATH
        except Exception:
            return bundled

    def scaler_path(self) -> str:
        if self.data.get("scaler_path"):
            return self.data["scaler_path"]
        bundled = _default_scaler_path()
        if os.path.exists(bundled):
            return bundled
        try:
            import opnsense_config as ocfg
            return ocfg.SCALER_PATH
        except Exception:
            return bundled

    def is_configured(self) -> bool:
        """True when the minimum needed to connect is present."""
        return bool(self.get("opnsense_host") and self.get("api_key")
                    and self.get("api_secret"))

    # ── apply user settings onto the FireSenseCli config module ─────────
    def apply_to_ocfg(self):
        """
        Patch the imported `opnsense_config` module so the existing
        OPNsenseCollector / OPNsenseActuator pick up the user's values.
        Only non-blank fields override the module defaults.
        """
        import opnsense_config as ocfg

        host = self.get("opnsense_host")
        if host:
            ocfg.OPNSENSE_HOST = host
        if self.get("api_key"):
            ocfg.API_KEY = self.get("api_key")
        if self.get("api_secret"):
            ocfg.API_SECRET = self.get("api_secret")
        ocfg.VERIFY_SSL = bool(self.get("verify_ssl"))

        if self.get("blocklist_alias"):
            ocfg.BLOCKLIST_ALIAS = self.get("blocklist_alias")

        # tighten rule UUIDs — only include the ones the user provided
        rule_uuids = {}
        if self.get("rule_tighten_inbound"):
            rule_uuids["tighten_inbound"] = self.get("rule_tighten_inbound")
        if self.get("rule_tighten_outbound"):
            rule_uuids["tighten_outbound"] = self.get("rule_tighten_outbound")
        if rule_uuids:
            ocfg.RULE_UUIDS = rule_uuids

        try:
            ocfg.DELTA_T = int(self.get("delta_t"))
        except (TypeError, ValueError):
            pass
        try:
            ocfg.LOG_FETCH_LIMIT = int(self.get("log_fetch_limit"))
        except (TypeError, ValueError):
            pass

        # self-traffic IPs (WAN IP + loopbacks)
        ocfg.OWN_IPS = {self.get("wan_ip"), "127.0.0.1", "::1", ""}

        # WAN interface identifiers (logical for rules, physical for log filtering)
        if self.get("wan_if"):
            ocfg.WAN_IF = self.get("wan_if")
        if self.get("wan_phys_if"):
            ocfg.WAN_PHYS_IF = self.get("wan_phys_if")

        return ocfg
