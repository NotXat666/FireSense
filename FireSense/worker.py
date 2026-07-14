"""
worker.py — DeploymentWorker QThread
Runs the FireRL inference loop in a background thread and emits Qt signals
for each window so the UI can update without blocking.
"""

import sys, os, time, csv, logging
import numpy as np

from PyQt6.QtCore import QThread, pyqtSignal

# ── Path setup — works in both normal run and PyInstaller .exe ───────────────
if getattr(sys, "frozen", False):
    _BASE = sys._MEIPASS
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

_AF_DIR = os.path.join(_BASE, "FireSenseCli")
if _AF_DIR not in sys.path:
    sys.path.insert(0, _AF_DIR)

# Light imports only at module load — the heavy ones (TensorFlow via dqn_agent,
# collector, actuator) are deferred into run() so importing this module and
# constructing the worker never freezes the UI thread.
import opnsense_config as ocfg
import pandas as pd


class WindowResult:
    """Data class for one inference window result."""
    __slots__ = ("window_id", "timestamp", "action", "action_name",
                 "latency_ms", "blocklist_size", "q_values",
                 "guard_fired", "is_attack")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class DeploymentWorker(QThread):
    """
    Runs the FireRL inference loop.

    Signals
    -------
    window_done(WindowResult)   emitted after each 30-s window
    log_line(str)               log message (info/warning/error)
    connected(bool)             OPNsense reachability changed
    finished_clean()            loop exited normally (user stopped)
    error(str)                  fatal exception in loop
    """

    window_done    = pyqtSignal(object)
    log_line       = pyqtSignal(str)
    connected      = pyqtSignal(bool)
    finished_clean = pyqtSignal()
    error          = pyqtSignal(str)
    rollback_hint  = pyqtSignal(bool, int, int)   # (aman?, jml_blok, jendela_aman)
    blocklist_changed = pyqtSignal(list)          # [(ip, umur_detik), …] per-IP

    ROLLBACK_SAFE_MIN = 5

    def __init__(self, cfg_manager=None, parent=None):
        """
        cfg_manager : ConfigManager  user settings (host, keys, model path, …).
                      If None, falls back to the module defaults in ocfg.
        """
        super().__init__(parent)
        self.cfgm = cfg_manager
        if cfg_manager is not None:
            cfg_manager.apply_to_ocfg()          # patch ocfg with user's values
            self.model_path  = cfg_manager.model_path()
            self.scaler_path = cfg_manager.scaler_path()
            self.delta_t     = int(cfg_manager.get("delta_t"))
        else:
            self.model_path  = ocfg.MODEL_PATH
            self.scaler_path = ocfg.SCALER_PATH
            self.delta_t     = ocfg.DELTA_T
        self._running    = False
        self._consec_safe = 0
        self._conn_state = None    # last emitted connectivity state (None = unknown)
        self._panic      = False   # set by request_panic(); handled in the loop thread
        self._rollback_hint_shown = False  # sudah beri tahu operator 'aman un-block'?
        self._unblock_all = False          # set request_unblock_all() (pemulihan)
        self._unblock_ips = []             # antrean unblock per-IP dari UI
        try:
            self._unblock_ttl_s = int(self.cfgm.get("unblock_ttl_s", 0)) if self.cfgm else 0
        except (TypeError, ValueError):
            self._unblock_ttl_s = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def stop(self):
        self._running = False

    def request_panic(self):
        """Ask the loop to unblock everything and disable tighten rules ASAP.
        Thread-safe: only sets a flag; the actual API calls run in the loop
        thread (which owns the actuator) to avoid races."""
        self._panic = True

    def request_unblock_all(self):
        """Pemulihan normal (bukan darurat): buka semua blokir + nonaktifkan
        tighten. Thread-safe; dieksekusi di loop thread pemilik actuator."""
        self._unblock_all = True

    def request_unblock_ip(self, ip):
        """Buka blokir SATU IP dari daftar (rollback per-IP). Thread-safe."""
        if ip:
            self._unblock_ips.append(ip)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _log(self, msg: str):
        self.log_line.emit(msg)

    def _set_connected(self, ok: bool):
        """Emit connected(...) only when the state actually changes, so the UI
        reflects live reachability (a successful window == connected) instead of
        being pinned by a single startup probe."""
        if ok != self._conn_state:
            self._conn_state = ok
            self.connected.emit(ok)

    def _check_attack(self, collector) -> bool:
        raw_df = getattr(collector, "_last_raw_df", None)
        if raw_df is None or len(raw_df) == 0:
            return False
        own_ips = getattr(ocfg, "OWN_IPS", {"10.0.2.4", "127.0.0.1", "::1", ""})
        ext = raw_df[~raw_df.get("src_ip", pd.Series(dtype=str)).isin(own_ips)] \
              if "src_ip" in raw_df.columns else pd.DataFrame()
        return len(ext) >= 50

    # ── Decision-log persistence (thesis evidence artifacts) ───────────────────

    def _results_dir(self) -> str:
        """Where to write the CSV evidence the laporan references.

        In a frozen .exe we must use a persistent, user-writable folder next to
        the executable — NOT sys._MEIPASS, which is a temp extraction dir wiped
        on exit. In dev we mirror the backend (`<repo>/results`) so dashboard.py
        and the paths cited in the laporan line up exactly."""
        if getattr(sys, "frozen", False):
            return os.path.join(os.path.dirname(sys.executable), "results")
        try:
            return os.path.dirname(ocfg.LOG_PATH)
        except Exception:
            return os.path.join(_BASE, "results")

    # 8 fitur konteks (urutan sama seperti environment.py / opnsense_collector.py)
    _CONTEXT_FEATURE_DESCS = [
        "Rolling mean reward (rata-rata reward jendela bergerak).",
        "Rolling std reward (deviasi standar reward jendela bergerak).",
        "Cumulative threat rate (serangan terdeteksi / total langkah).",
        "Cumulative false-positive rate (blokir salah / total langkah).",
        "Progres langkah dalam episode, dinormalisasi 0..1.",
        "Aksi terakhir yang diambil, dinormalisasi 0..1 (aksi/3).",
        "Jumlah serangan beruntun, dinormalisasi 0..1.",
        "Proksi jumlah rule aktif, dinormalisasi 0..1 (dibagi 100).",
    ]

    def _write_data_dictionary(self, results_dir, cfg):
        """Tulis kamus data (data dictionary) pendamping window_decisions.csv.

        Mengikuti anjuran Frictionless Data / CSVW / ESS-DIVE: satu file tabular
        yang mendeskripsikan setiap kolom (nama, tipe, satuan, keterangan) agar
        artefak bukti TA dapat direproduksi tanpa membaca kode."""
        try:
            from state_engineering import FLOW_FEATURE_NAMES
        except Exception:
            FLOW_FEATURE_NAMES = [f"flow_feature_{i}" for i in range(14)]

        action_names = {0: "maintain", 1: "block_ip", 2: "tighten", 3: "rollback"}
        n_flow = getattr(cfg, "N_FLOW_FEATURES", 14)

        rows = [
            ("window_id", "integer", "-",
             "Nomor urut jendela inferensi Δt=30 detik, dimulai dari 0."),
            ("timestamp", "datetime (ISO 8601)", "-",
             "Waktu keputusan, ISO 8601 dengan offset zona waktu lokal "
             "(mis. 2026-07-06T14:30:00+07:00)."),
            ("action", "integer", "-",
             "ID aksi DQN: " + ", ".join(f"{k}={v}" for k, v in action_names.items()) + "."),
            ("action_name", "string", "-",
             "Nama aksi yang benar-benar dieksekusi (setelah rollback-guard)."),
            ("latency_ms", "number", "milidetik",
             "Latensi dari awal jendela hingga aksi diterapkan ke OPNsense."),
            ("blocklist_size", "integer", "cacah",
             "Jumlah IP pada alias blocklist setelah aksi diterapkan."),
        ]
        for i in range(cfg.NUM_ACTIONS):
            rows.append((f"q{i}", "number", "-",
                         f"Q-value aksi {i} ({action_names.get(i, i)}) dari jaringan DQN."))
        for i in range(cfg.STATE_DIM):
            if i < n_flow:
                fname = FLOW_FEATURE_NAMES[i] if i < len(FLOW_FEATURE_NAMES) else f"flow_{i}"
                rows.append((f"s{i}", "number", "terstandardisasi (z-score)",
                             f"Fitur flow rata-rata per-jendela (distandardisasi via scaler.pkl): {fname}."))
            else:
                ci = i - n_flow
                desc = self._CONTEXT_FEATURE_DESCS[ci] if ci < len(self._CONTEXT_FEATURE_DESCS) \
                    else f"Fitur konteks {ci}."
                rows.append((f"s{i}", "number", "ternormalisasi", desc))

        dict_path = os.path.join(results_dir, "window_decisions.dictionary.csv")
        with open(dict_path, "w", newline="", encoding="utf-8") as df:
            dw = csv.writer(df, lineterminator="\r\n")
            dw.writerow(["column", "type", "unit", "description"])
            dw.writerows(rows)
        self._log(f"[FireSense] Kamus data ditulis → {dict_path}")

    def _open_decision_log(self, cfg):
        """Open window_decisions.csv (append) + create traffic_snapshot/.
        Returns (writer, file, snapshot_dir); (None, None, None) on failure so
        deployment continues even if the results dir is not writable."""
        try:
            results_dir  = self._results_dir()
            snapshot_dir = os.path.join(results_dir, "traffic_snapshot")
            os.makedirs(snapshot_dir, exist_ok=True)
            decisions_path = os.path.join(results_dir, "window_decisions.csv")
            header_written = os.path.exists(decisions_path)
            # RFC 4180: UTF-8 encoding + CRLF line terminator, satu baris header,
            # jumlah kolom konsisten, quoting ditangani modul csv.
            f = open(decisions_path, "a", newline="", encoding="utf-8")
            w = csv.writer(f, lineterminator="\r\n")
            if not header_written:
                w.writerow(
                    ["window_id", "timestamp", "action", "action_name",
                     "latency_ms", "blocklist_size"]
                    + [f"q{i}" for i in range(cfg.NUM_ACTIONS)]
                    + [f"s{i}" for i in range(cfg.STATE_DIM)]
                )
                f.flush()
            self._write_data_dictionary(results_dir, cfg)
            self._log(f"[FireSense] Mencatat keputusan → {decisions_path}")
            self._log(f"[FireSense] Snapshot trafik per jendela → {snapshot_dir}")
            return w, f, snapshot_dir
        except Exception as e:
            self._log(f"[WARNING] Tidak bisa membuat log keputusan CSV: {e}")
            return None, None, None

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        import datetime as _dt
        self._running = True
        ACTION_NAMES = {0: "maintain", 1: "block_ip", 2: "tighten", 3: "rollback"}

        try:
            # Heavy imports happen here (inside the thread) to keep the UI responsive
            self._log("[FireSense] Menyiapkan TensorFlow & model …")
            import config as cfg
            from dqn_agent          import DQNAgent
            from opnsense_collector import OPNsenseCollector
            from opnsense_actuator  import OPNsenseActuator

            self._log(f"[FireSense] Memuat model: {os.path.basename(self.model_path)}")
            agent = DQNAgent(state_dim=cfg.STATE_DIM, num_actions=cfg.NUM_ACTIONS)
            agent.load(self.model_path)
            self._log("[FireSense] Model dimuat.")

            collector = OPNsenseCollector(scaler_path=self.scaler_path)
            actuator  = OPNsenseActuator()
            self._log("[FireSense] Kolektor & aktuator siap.")

            # Connectivity check — OPNsense is slow to answer when cold (~4s) and
            # firmware/info is one of the heavier endpoints, so use a generous
            # (connect, read) timeout. A false negative here is only advisory:
            # the loop below re-derives the real state from each window's success.
            try:
                import requests
                r = requests.get(
                    ocfg.OPNSENSE_HOST + "/api/core/firmware/info",
                    auth=(ocfg.API_KEY, ocfg.API_SECRET),
                    verify=ocfg.VERIFY_SSL, timeout=(6, 25),
                )
                r.raise_for_status()
                self._set_connected(True)
                self._log(f"[FireSense] OPNsense terjangkau di {ocfg.OPNSENSE_HOST}")
            except Exception as e:
                self._set_connected(False)
                self._log(f"[WARNING] Uji OPNsense gagal (loop akan mengulang): {e}")

        except Exception as e:
            self.error.emit(f"Inisialisasi gagal: {e}")
            return

        window_idx     = 0
        self._consec_safe = 0

        # Persistent decision log + traffic snapshots (mirrors opnsense_inference.py)
        dec_writer, dec_file, snapshot_dir = self._open_decision_log(cfg)

        self._log("[FireSense] Memulai loop inferensi …")

        while self._running:
            t_start = time.time()

            # Emergency panic requested from the UI — handle before the next window
            if self._panic:
                self._panic = False
                self._log("[PANIC] Membuka semua blokir & menonaktifkan rule tighten…")
                try:
                    res = actuator.panic_reset()
                    done = ", ".join(res["changes"]) or "tidak ada yang perlu dibuka"
                    self._log(f"[PANIC] Selesai: {done}")
                    if res.get("errors"):
                        self._log(f"[WARNING] Panik: {'; '.join(res['errors'])}")
                    if res.get("apply_ok") is False:
                        self._log("[WARNING] Panik: filter/apply gagal, cek OPNsense manual")
                except Exception as e:
                    self._log(f"[ERROR] Panik gagal: {e}")

            # Pemulihan normal — buka SEMUA blokir (dari banner/tombol Buka Blokir)
            if self._unblock_all:
                self._unblock_all = False
                self._log("[PEMULIHAN] Membuka semua blokir & menonaktifkan tighten…")
                try:
                    res = actuator.panic_reset()
                    done = ", ".join(res["changes"]) or "tidak ada yang perlu dibuka"
                    self._log(f"[PEMULIHAN] Selesai: {done}")
                    self._rollback_hint_shown = False
                except Exception as e:
                    self._log(f"[ERROR] Pemulihan gagal: {e}")

            # Unblock per-IP (dari panel blocklist) — antrean diproses satu per satu
            while self._unblock_ips:
                ip = self._unblock_ips.pop(0)
                try:
                    res = actuator.unblock_ip(ip)
                    if res.get("errors"):
                        self._log(f"[UNBLOCK] {ip} gagal: {'; '.join(res['errors'])}")
                    else:
                        self._log(f"[UNBLOCK] IP {ip} dibuka blokirnya.")
                except Exception as e:
                    self._log(f"[ERROR] Unblock {ip} gagal: {e}")

            try:
                # 1. Collect state
                state = collector.collect_window()

                # 2. Detect attack before inference (for guard)
                is_attack = self._check_attack(collector)
                if is_attack:
                    self._consec_safe = 0
                else:
                    self._consec_safe += 1

                # 2b. TTL auto-expiry (opsional, gaya fail2ban bantime): buka blokir
                # IP yang sudah melewati unblock_ttl_s DAN tak ada serangan aktif.
                # blocklist_detail() = snapshot, aman diiterasi saat unblock memodifikasi state.
                if self._unblock_ttl_s > 0 and not is_attack:
                    now = time.time()
                    for ip, since in actuator.blocklist_detail():
                        if since and (now - since) >= self._unblock_ttl_s:
                            res = actuator.unblock_ip(ip)
                            if not res.get("errors"):
                                self._log(f"[TTL] IP {ip} auto-unblock "
                                          f"(aman > {self._unblock_ttl_s}s).")

                # 3. DQN inference
                action, q_values = agent.predict_with_qvalues(state)

                # 4. Rollback guard
                guard_fired = False
                if action == 3:
                    safe = (
                        actuator.blocklist_size > 0
                        and not is_attack
                        and self._consec_safe >= self.ROLLBACK_SAFE_MIN
                    )
                    if not safe:
                        guard_fired = True
                        if is_attack:
                            # Under attack, action 3 reflects the model's training
                            # semantics (reset-both = BLOCKING), not deployment
                            # rollback. Honor that intent: take the best BLOCKING
                            # action (block_ip/tighten) rather than idling on maintain.
                            action = max(cfg.BLOCKING_ACTIONS, key=lambda a: q_values[a])
                            self._log(
                                f"[RollbackGuard] Rollback saat serangan → "
                                f"{ACTION_NAMES[action]} (aksi blocking terbaik; "
                                f"q={ {a: round(float(q_values[a]), 2) for a in sorted(cfg.BLOCKING_ACTIONS)} })"
                            )
                        else:
                            self._log(
                                f"[RollbackGuard] Suppressed rollback "
                                f"(blk={actuator.blocklist_size}, atk={is_attack}, "
                                f"safe_wins={self._consec_safe}/{self.ROLLBACK_SAFE_MIN}) → maintain"
                            )
                            action = 0

                # 5. Execute
                suspicious_ip = getattr(collector, "suspicious_ip", None) if action == 1 else None
                result = actuator.execute_action(action, suspicious_ip=suspicious_ip)

                # 5b. Surface API failures that were previously swallowed silently
                if result.get("errors"):
                    self._log(f"[WARNING] OPNsense: {'; '.join(result['errors'])}")
                if result.get("apply_ok") is False:
                    self._log("[WARNING] filter/apply gagal, perubahan mungkin belum diberlakukan")

                # 6. Timing
                t_eff     = result.get("t_effective", time.time())
                lat_ms    = (t_eff - t_start) * 1000.0

                # 7. Update context
                collector.update_context(
                    action,
                    blocked=(action in cfg.BLOCKING_ACTIONS),
                    is_attack_hint=is_attack,
                    blocklist_size=actuator.blocklist_size,
                )

                # 8. Build result and emit
                ts = _dt.datetime.now().strftime("%H:%M:%S")
                wr = WindowResult(
                    window_id    = window_idx,
                    timestamp    = ts,
                    action       = action,
                    action_name  = ACTION_NAMES[action],
                    latency_ms   = lat_ms,
                    blocklist_size = actuator.blocklist_size,
                    q_values     = list(q_values),
                    guard_fired  = guard_fired,
                    is_attack    = is_attack,
                )
                # A completed window means OPNsense answered — the loop is the
                # authoritative connectivity signal, self-healing the startup probe.
                self._set_connected(True)
                self.window_done.emit(wr)
                self._log(
                    f"[Jdl {window_idx:4d}] {ACTION_NAMES[action]:<10} "
                    f"| lat={lat_ms:.0f}ms | blk={actuator.blocklist_size}"
                    + (" | 🛡 guard" if guard_fired else "")
                )

                # 8b. Beri tahu operator kapan AMAN melakukan un-block manual (Panik).
                # Syarat sama dengan kondisi 'safe' RollbackGuard: ada IP diblokir,
                # tidak ada serangan aktif, dan >= ROLLBACK_SAFE_MIN jendela aman
                # berturut-turut — persis titik di mana auto-rollback akan menyala.
                rollback_ready = (actuator.blocklist_size > 0
                                  and not is_attack
                                  and self._consec_safe >= self.ROLLBACK_SAFE_MIN)
                if rollback_ready and not self._rollback_hint_shown:
                    self._rollback_hint_shown = True
                    self._log(
                        f"[SARAN] ✅ Aman untuk un-block: {actuator.blocklist_size} IP diblokir, "
                        f"{self._consec_safe} jendela aman berturut-turut tanpa serangan. "
                        f"Klik 'Buka Blokir' bila ancaman dinilai selesai."
                    )
                elif not rollback_ready and self._rollback_hint_shown:
                    # Kondisi aman batal (serangan muncul lagi / blocklist sudah kosong)
                    self._rollback_hint_shown = False
                    if is_attack and actuator.blocklist_size > 0:
                        self._log("[SARAN] ⚠ Batalkan rencana un-block — serangan terdeteksi lagi.")

                # 8c. Sinyal ke GUI: status kesiapan un-block (untuk banner) +
                # detail blocklist per-IP (untuk panel/tabel).
                self.rollback_hint.emit(bool(rollback_ready),
                                        actuator.blocklist_size, self._consec_safe)
                # Kirim waktu-mulai-blokir (epoch), bukan umur — agar GUI bisa
                # menghitung durasi hidup per-detik lewat QTimer sendiri.
                self.blocklist_changed.emit(
                    [(ip, float(since) if since else 0.0)
                     for ip, since in actuator.blocklist_detail()])

                # 9. Persist decision row + raw traffic snapshot (thesis evidence)
                if dec_writer is not None:
                    try:
                        # ISO 8601 lengkap dengan offset zona waktu lokal,
                        # mis. 2026-07-06T14:30:00+07:00 (tidak ambigu antar zona).
                        iso = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
                        dec_writer.writerow(
                            [window_idx, iso, action, ACTION_NAMES[action],
                             f"{lat_ms:.3f}", actuator.blocklist_size]
                            + list(q_values)
                            + (state.tolist() if hasattr(state, "tolist") else list(state))
                        )
                        dec_file.flush()
                        raw_df = getattr(collector, "_last_raw_df", None)
                        if raw_df is not None and len(raw_df) > 0:
                            raw_df.to_csv(
                                os.path.join(snapshot_dir, f"window_{window_idx:06d}.csv"),
                                index=False)
                    except Exception as e:
                        self._log(f"[WARNING] Gagal menulis log jendela {window_idx}: {e}")

                window_idx += 1

            except Exception as e:
                self._set_connected(False)
                self._log(f"[ERROR] Jendela {window_idx}: {e}")

            # Sleep remainder of Δt
            elapsed = time.time() - t_start
            sleep_s = max(0.0, self.delta_t - elapsed)
            # Sleep in small chunks so stop() is responsive
            t_wake = time.time() + sleep_s
            while self._running and not self._panic and time.time() < t_wake:
                time.sleep(0.2)

        if dec_file is not None:
            try:
                dec_file.close()
            except Exception:
                pass

        self._log("[FireSense] Loop inferensi dihentikan.")
        self.finished_clean.emit()
