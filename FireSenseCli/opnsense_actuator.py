# opnsense_actuator.py — Execute DQN actions on OPNsense via REST API

import csv
import os
import time
import logging
import datetime
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import opnsense_config as ocfg
import config

log = logging.getLogger(__name__)

# Action indices (must match environment.py)
A_MAINTAIN = 0
A_BLOCK_IP = 1
A_TIGHTEN  = 2
A_ROLLBACK = 3


class OPNsenseActuator:
    """
    Translates DQN agent actions into OPNsense API calls.

    a0 — maintain     : no-op
    a1 — block_ip     : add IP to alias rl_blocklist → apply
    a2 — tighten      : enable restrictive rules → apply
    a3 — rollback     : remove oldest IPs from alias, disable tighten rules
    """

    def __init__(self):
        self.host    = ocfg.OPNSENSE_HOST
        self.auth    = (ocfg.API_KEY, ocfg.API_SECRET)
        self.verify  = ocfg.VERIFY_SSL
        self.timeout = 15

        self._session   = requests.Session()
        self._session.auth   = self.auth
        self._session.verify = self.verify

        # Track local state (mirrors what we sent to OPNsense)
        self.blocklist       = []    # list of IP strings in insertion order
        self.block_times     = {}    # ip -> epoch saat diblokir (untuk umur & TTL)
        self.rules_tightened = False

        # Persistent rule change log
        self._rule_log_path = os.path.join(
            os.path.dirname(ocfg.LOG_PATH), "rule_changes.csv"
        )
        os.makedirs(os.path.dirname(self._rule_log_path), exist_ok=True)
        if not os.path.exists(self._rule_log_path):
            with open(self._rule_log_path, "w", newline="") as f:
                csv.writer(f).writerow(["timestamp", "action", "detail", "applied"])

    # ── Public interface ──────────────────────────────────────────────────────

    def execute_action(self, action: int,
                       suspicious_ip: str = None) -> dict:
        """
        Execute the given action.

        Parameters
        ----------
        action        : int  0–3
        suspicious_ip : str  required when action == A_BLOCK_IP

        Returns
        -------
        result dict with keys: action, changes, t_effective
        """
        t_start = time.time()

        if action == A_MAINTAIN:
            result = self._action_maintain()
        elif action == A_BLOCK_IP:
            result = self._action_block_ip(suspicious_ip)
        elif action == A_TIGHTEN:
            result = self._action_tighten()
        elif action == A_ROLLBACK:
            result = self._action_rollback()
        else:
            log.warning(f"[Actuator] Unknown action {action}")
            result = {"action": "unknown", "changes": []}

        result["t_effective"] = time.time()
        result["latency_s"]   = result["t_effective"] - t_start
        log.info(f"[Actuator] {result}")
        return result

    @property
    def blocklist_size(self) -> int:
        return len(self.blocklist)

    def blocklist_detail(self) -> list:
        """Detail tiap IP terblokir: [(ip, blocked_since_epoch), …] urut insertion."""
        return [(ip, self.block_times.get(ip)) for ip in self.blocklist]

    def unblock_ip(self, ip: str) -> dict:
        """Buka blokir SATU IP (rollback per-IP). Hapus dari alias + state lokal."""
        if ip not in self.blocklist:
            return {"action": "unblock_ip", "ip": ip, "changes": [],
                    "errors": [], "note": "tidak sedang diblokir"}
        endpoint = ocfg.ENDPOINTS["alias_delete"].format(alias=ocfg.BLOCKLIST_ALIAS)
        resp = self._api_call("POST", endpoint, data={"address": ip})
        if resp and resp.get("status") in ("ok", "done"):
            self.blocklist.remove(ip)
            self.block_times.pop(ip, None)
            apply_ok = self._apply_firewall()
            self._log_rule_change("unblock_ip", f"unblocked {ip}", True)
            return {"action": "unblock_ip", "ip": ip, "changes": [f"unblocked {ip}"],
                    "apply_ok": apply_ok, "errors": []}
        self._log_rule_change("unblock_ip", f"failed {ip}", False)
        return {"action": "unblock_ip", "ip": ip, "changes": [],
                "errors": [f"OPNsense menolak unblock {ip}"]}

    # ── Action implementations ────────────────────────────────────────────────

    def _action_maintain(self) -> dict:
        return {"action": "maintain", "changes": []}

    def _action_block_ip(self, ip: str) -> dict:
        if not ip:
            return {"action": "block_ip", "changes": [], "error": "no ip provided"}
        if ip in self.blocklist:
            return {"action": "block_ip", "changes": [], "note": "already blocked"}

        endpoint = ocfg.ENDPOINTS["alias_add"].format(alias=ocfg.BLOCKLIST_ALIAS)
        resp = self._api_call("POST", endpoint, data={"address": ip})
        if resp and resp.get("status") in ("ok", "done"):
            self.blocklist.append(ip)
            self.block_times[ip] = time.time()
            apply_ok = self._apply_firewall()
            self._log_rule_change("block_ip", f"blocked {ip}", True)
            return {"action": "block_ip", "ip": ip, "changes": [f"blocked {ip}"],
                    "applied": True, "apply_ok": apply_ok, "errors": []}
        self._log_rule_change("block_ip", f"failed {ip}", False)
        return {"action": "block_ip", "ip": ip, "changes": [], "applied": False,
                "resp": resp, "errors": [f"OPNsense menolak block {ip}"]}

    def _action_tighten(self) -> dict:
        if self.rules_tightened:
            log.info("[Actuator] Tighten rules already active — skipping toggle")
            return {"action": "tighten", "changes": [], "note": "already tightened"}
        changes, errors = [], []
        for rule_name, uuid in ocfg.RULE_UUIDS.items():
            endpoint = ocfg.ENDPOINTS["rule_toggle"].format(uuid=uuid)
            resp = self._api_call("POST", endpoint)
            if resp:
                changes.append(f"enabled rule {rule_name}")
            else:
                errors.append(f"toggle rule {rule_name} gagal")
        apply_ok = self._apply_firewall()
        self.rules_tightened = True
        for rule_name in ocfg.RULE_UUIDS:
            self._log_rule_change("tighten", f"enabled {rule_name}", True)
        return {"action": "tighten", "changes": changes,
                "errors": errors, "apply_ok": apply_ok}

    def _action_rollback(self) -> dict:
        changes, errors = [], []
        n_remove = max(1, len(self.blocklist) // config.ROLLBACK_FRACTION)
        removed  = self.blocklist[:n_remove]

        for ip in removed:
            endpoint = ocfg.ENDPOINTS["alias_delete"].format(alias=ocfg.BLOCKLIST_ALIAS)
            resp = self._api_call("POST", endpoint, data={"address": ip})
            if resp and resp.get("status") in ("ok", "done"):
                changes.append(f"unblocked {ip}")
            else:
                errors.append(f"unblock {ip} gagal")

        self.blocklist = self.blocklist[n_remove:]
        for ip in removed:
            self.block_times.pop(ip, None)

        # Disable tightened rules if they were active
        if self.rules_tightened:
            for rule_name, uuid in ocfg.RULE_UUIDS.items():
                endpoint = ocfg.ENDPOINTS["rule_toggle"].format(uuid=uuid)
                self._api_call("POST", endpoint)
                changes.append(f"disabled rule {rule_name}")
            self.rules_tightened = False

        apply_ok = self._apply_firewall()
        for ip in removed:
            self._log_rule_change("rollback", f"unblocked {ip}", True)
        return {"action": "rollback", "ips_removed": removed, "changes": changes,
                "errors": errors, "apply_ok": apply_ok}

    def panic_reset(self) -> dict:
        """Emergency stop: remove EVERY blocked IP and disable all tighten rules,
        then apply. Called from the FireSense Panic button — restores traffic to
        the pre-deployment state in one shot (unlike rollback which is partial)."""
        changes, errors = [], []
        for ip in list(self.blocklist):
            endpoint = ocfg.ENDPOINTS["alias_delete"].format(alias=ocfg.BLOCKLIST_ALIAS)
            resp = self._api_call("POST", endpoint, data={"address": ip})
            if resp and resp.get("status") in ("ok", "done"):
                changes.append(f"unblocked {ip}")
            else:
                errors.append(f"unblock {ip} gagal")
        self.blocklist = []
        self.block_times.clear()

        if self.rules_tightened:
            for rule_name, uuid in ocfg.RULE_UUIDS.items():
                endpoint = ocfg.ENDPOINTS["rule_toggle"].format(uuid=uuid)
                self._api_call("POST", endpoint)
                changes.append(f"disabled rule {rule_name}")
            self.rules_tightened = False

        apply_ok = self._apply_firewall()
        for c in changes:
            self._log_rule_change("panic", c, True)
        return {"action": "panic", "changes": changes,
                "errors": errors, "apply_ok": apply_ok}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log_rule_change(self, action: str, detail: str, applied: bool):
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        with open(self._rule_log_path, "a", newline="") as f:
            csv.writer(f).writerow([ts, action, detail, applied])

    def _apply_firewall(self) -> bool:
        resp = self._api_call("POST", ocfg.ENDPOINTS["filter_apply"])
        if resp is None:
            log.warning("[Actuator] filter/apply failed — change may not be enforced")
            return False
        return True

    def _api_call(self, method: str, endpoint: str,
                  data: dict = None, retries: int = 2) -> dict | None:
        url = self.host + endpoint
        for attempt in range(retries + 1):
            try:
                resp = self._session.request(
                    method, url, json=data, timeout=self.timeout
                )
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as exc:
                log.warning(f"[Actuator] API {method} {endpoint} attempt {attempt+1} failed: {exc}")
                if attempt < retries:
                    time.sleep(1)
        # Graceful degradation — caller handles None
        return None
