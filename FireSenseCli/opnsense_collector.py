# opnsense_collector.py — Collect OPNsense logs → per-flow state vector
#
# Deployment strategy: each individual OPNsense log entry is mapped to the
# same 14-feature schema used during per-flow training, then the scaler
# (fitted on training data) is applied, and context features are appended.

import time
import logging
import numpy as np
import pandas as pd
import joblib
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import opnsense_config as ocfg
from state_engineering import extract_flow_features

log = logging.getLogger(__name__)


class OPNsenseCollector:
    """
    Fetches the most recent firewall log entry from OPNsense and converts it
    to the same 22-dim state vector used during per-flow DQN training.

    For each Δt window:
      1. Fetch log entries via API
      2. Map OPNsense fields → Kaggle column schema (per entry)
      3. For each entry, call extract_flow_features() → (14,) raw vector
      4. Apply saved StandardScaler
      5. Append 8 context features → (22,) state vector
      6. Return the LAST entry's state (most recent decision to make)
    """

    def __init__(self, scaler_path: str = None):
        self.host    = ocfg.OPNSENSE_HOST
        self.auth    = (ocfg.API_KEY, ocfg.API_SECRET)
        self.verify  = ocfg.VERIFY_SSL
        self.timeout = (5, 10)  # (connect_timeout, read_timeout) — separate so SSL failure != slow response
        self._consecutive_fetch_failures = 0

        scaler_path = scaler_path or ocfg.SCALER_PATH
        self.scaler = joblib.load(scaler_path)
        log.info(f"[Collector] Scaler loaded from {scaler_path}")

        # Context state (maintained between calls)
        self.blocklist_size          = 0
        self.last_action             = 0
        self.consecutive_same_action = 0
        self._threat_count           = 0
        self._fp_count               = 0
        self._step                   = 0
        self._rule_count             = 1
        self._consec_attack          = 0
        self._last_raw_df            = pd.DataFrame()

    # ── Public API ────────────────────────────────────────────────────────────

    def collect_window(self) -> np.ndarray:
        """
        Fetch the latest log entries, aggregate per external source IP,
        and return the state vector for the most suspicious source.

        This aggregation converts N individual SYN probes (each Packets=1)
        from the same source into one row with Packets=N, which is
        critical for the DQN to detect volume-based attacks (port scans, floods).

        Returns np.ndarray shape (STATE_DIM,) = (22,)
        """
        import config

        logs = self._fetch_firewall_logs()
        df   = self._map_opnsense_to_features(logs)
        self._last_raw_df = df

        if len(df) == 0:
            return np.zeros(config.STATE_DIM, dtype=np.float32)

        # Identify the OPNsense WAN IP so we ignore self-generated traffic
        OWN_IPS = getattr(ocfg, "OWN_IPS", {"10.0.2.4", "127.0.0.1", "::1", ""})
        ext_df = df[~df["src_ip"].isin(OWN_IPS)] if "src_ip" in df.columns else pd.DataFrame()

        self.suspicious_ip = None  # reset each window

        if len(ext_df) == 0:
            # No external traffic in this window — use last entry as fallback
            row = df.iloc[-1]
        else:
            # Aggregate per source IP: sum packets and bytes to capture volume
            agg = ext_df.groupby("src_ip", sort=False).agg(
                src_port_mode   = ("Source Port",          lambda x: x.mode()[0]),
                dst_port_mode   = ("Destination Port",     lambda x: x.mode()[0]),
                nat_src_mode    = ("NAT Source Port",      lambda x: x.mode()[0]),
                nat_dst_mode    = ("NAT Destination Port", lambda x: x.mode()[0]),
                total_bytes     = ("Bytes",                "sum"),
                total_bytes_s   = ("Bytes Sent",           "sum"),
                total_bytes_r   = ("Bytes Received",       "sum"),
                total_pkts      = ("Packets",              "sum"),
                total_pkts_s    = ("pkts_sent",            "sum"),
                total_pkts_r    = ("pkts_received",        "sum"),
            ).reset_index()

            agg["Elapsed Time (sec)"] = float(ocfg.DELTA_T)

            # Most suspicious IP = highest packet count (volume attack indicator)
            most_suspicious_idx = agg["total_pkts"].idxmax()
            agg_row = agg.iloc[most_suspicious_idx]

            row = pd.Series({
                "src_ip":                   agg_row["src_ip"],
                "Source Port":              float(agg_row["src_port_mode"]),
                "Destination Port":         float(agg_row["dst_port_mode"]),
                "NAT Source Port":          float(agg_row["nat_src_mode"]),
                "NAT Destination Port":     float(agg_row["nat_dst_mode"]),
                "Bytes":                    float(agg_row["total_bytes"]),
                "Bytes Sent":               float(agg_row["total_bytes_s"]),
                "Bytes Received":           float(agg_row["total_bytes_r"]),
                "Packets":                  float(agg_row["total_pkts"]),
                "Elapsed Time (sec)":       float(ocfg.DELTA_T),
                "pkts_sent":                float(agg_row["total_pkts_s"]),
                "pkts_received":            float(agg_row["total_pkts_r"]),
                "Action":                   "allow",
            })
            self.suspicious_ip = str(agg_row["src_ip"])
            log.info(
                f"[Collector] Window: {len(df)} entries, "
                f"{len(ext_df)} external from {agg['src_ip'].nunique()} IPs. "
                f"Most suspicious: {agg_row['src_ip']} "
                f"({int(agg_row['total_pkts'])} pkts, {int(agg_row['total_bytes'])} bytes)"
            )

        raw_feat = extract_flow_features(row)                   # (14,)
        scaled   = self.scaler.transform(raw_feat.reshape(1, -1))[0].astype(np.float32)

        # Build context (8 features — same order as environment.py)
        self._step += 1
        mean_r  = 0.0          # no reward history available at deployment
        std_r   = 0.0
        thr_r   = self._threat_count / max(self._step, 1)
        fp_r    = self._fp_count / max(self._step, 1)
        prog    = min(self._step / config.STEPS_PER_EPISODE, 1.0)
        la_norm = self.last_action / (config.NUM_ACTIONS - 1)
        atk_seq = min(self._consec_attack, config.CONTEXT_MAX_CONSEC_ATK) / config.CONTEXT_MAX_CONSEC_ATK
        rule_n  = min(self._rule_count, config.CONTEXT_MAX_RULE_COUNT) / config.CONTEXT_MAX_RULE_COUNT

        ctx = np.array(
            [mean_r, std_r, thr_r, fp_r, prog, la_norm, atk_seq, rule_n],
            dtype=np.float32,
        )
        return np.concatenate([scaled, ctx])

    def update_context(self, action: int, blocked: bool,
                       is_attack_hint: bool = False, blocklist_size: int = 0):
        """Called by inference loop after each action execution."""
        import config
        self.consecutive_same_action = (
            self.consecutive_same_action + 1 if action == self.last_action else 0
        )
        self.last_action    = action
        self.blocklist_size = blocklist_size
        if action in config.BLOCKING_ACTIONS:
            self._rule_count = min(self._rule_count + 1, 200)
        if is_attack_hint:
            self._threat_count  += 1
            self._consec_attack += 1
        else:
            self._consec_attack = 0
        if blocked and not is_attack_hint:
            self._fp_count += 1

    # ── Internal ──────────────────────────────────────────────────────────────

    def _fetch_firewall_logs(self) -> list:
        """Fetch log entries and filter to only those within the current DELTA_T window.

        OPNsense keeps a large circular log buffer. Without time filtering, stale
        entries from a previous scan would persist and keep triggering block_ip
        long after the actual attack ended. Filtering by __timestamp__ ensures the
        state vector reflects only what happened in the last Δt seconds.

        Retry once on SSLError — lighttpd can transiently close connections mid-handshake
        when under load. A 2-second pause is usually enough for it to recover.
        """
        import datetime as _dt
        import ssl
        from requests.exceptions import SSLError as RequestsSSLError

        url = self.host + ocfg.ENDPOINTS["firewall_log"]

        def _do_fetch():
            resp = requests.get(
                url, auth=self.auth,
                params={"limit": ocfg.LOG_FETCH_LIMIT},
                verify=self.verify, timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()

        try:
            data = _do_fetch()
        except RequestsSSLError as exc:
            log.warning(f"[Collector] SSL error on fetch, retrying in 2s: {exc}")
            time.sleep(2)
            try:
                data = _do_fetch()
            except Exception as exc2:
                self._consecutive_fetch_failures += 1
                if self._consecutive_fetch_failures >= 3:
                    log.error(
                        f"[Collector] {self._consecutive_fetch_failures} consecutive fetch failures — "
                        "OPNsense API may be down. Check lighttpd/configd status."
                    )
                log.warning(f"[Collector] Log fetch failed: {exc2}. Returning empty.")
                return []
        except Exception as exc:
            self._consecutive_fetch_failures += 1
            if self._consecutive_fetch_failures >= 3:
                log.error(
                    f"[Collector] {self._consecutive_fetch_failures} consecutive fetch failures — "
                    "OPNsense API may be down. Check lighttpd/configd status."
                )
            log.warning(f"[Collector] Log fetch failed: {exc}. Returning empty.")
            return []

        self._consecutive_fetch_failures = 0
        logs = data if isinstance(data, list) else data.get("digest", data.get("logs", []))

        # Keep only entries within the current window (2× DELTA_T for clock skew tolerance)
        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=ocfg.DELTA_T * 2)
        filtered = []
        for entry in logs:
            ts_raw = entry.get("__timestamp__", "")
            if not ts_raw:
                filtered.append(entry)  # no timestamp → keep
                continue
            try:
                ts = _dt.datetime.fromisoformat(ts_raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=_dt.timezone.utc)
                if ts >= cutoff:
                    filtered.append(entry)
            except ValueError:
                filtered.append(entry)  # unparseable → keep

        log.debug(f"[Collector] Log fetch: {len(logs)} total, {len(filtered)} in window")
        return filtered

    def _map_opnsense_to_features(self, logs: list) -> pd.DataFrame:
        """Map OPNsense log entries to Kaggle dataset column schema."""
        if not logs:
            return pd.DataFrame()

        rows = []
        for entry in logs:
            # Only consider WAN traffic — excludes LAN management/API traffic.
            # Physical NIC name is configurable (FireSense Setup) so this is not
            # tied to the "em0" of one particular lab box.
            wan_phys = str(getattr(ocfg, "WAN_PHYS_IF", "em0")).lower()
            iface = str(entry.get("interface", "")).lower()
            if iface and wan_phys and iface != wan_phys:
                continue

            action_raw = str(entry.get("action", "pass")).lower()
            action     = "allow" if action_raw == "pass" else "deny"
            length     = float(entry.get("length", 0) or 0)

            # OPNsense uses field "dir" (not "direction") and "srcport"/"dstport"
            direction = str(entry.get("dir", "in")).lower()
            if direction == "in":
                bytes_s = length
                bytes_r = 0.0
                pkts_s  = 1
                pkts_r  = 0
            else:
                bytes_s = 0.0
                bytes_r = length
                pkts_s  = 0
                pkts_r  = 1

            rows.append({
                "src_ip":                   str(entry.get("src", "") or ""),
                "Source Port":              int(entry.get("srcport", 0)  or 0),
                "Destination Port":         int(entry.get("dstport", 0)  or 0),
                "NAT Source Port":          int(entry.get("srcport", 0)  or 0),
                "NAT Destination Port":     int(entry.get("dstport", 0)  or 0),
                "Bytes":                    length,
                "Bytes Sent":               bytes_s,
                "Bytes Received":           bytes_r,
                "Packets":                  1,
                "Elapsed Time (sec)":       float(ocfg.DELTA_T),
                "pkts_sent":                pkts_s,
                "pkts_received":            pkts_r,
                "Action":                   action,
            })
        return pd.DataFrame(rows)
