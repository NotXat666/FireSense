"""
provision.py — Auto-setup OPNsense objects that FireSense needs.

Aplikasi ini ditujukan untuk user yang ingin mengamankan jaringan dengan OPNsense
tapi belum tahu cara mengonfigurasinya. Modul ini membuat OTOMATIS semua objek
firewall yang diperlukan lewat REST API, jadi user tidak perlu membukanya manual:

  1. Alias `rl_blocklist` (type host)   → tempat DQN menaruh IP yang diblokir.
  2. Rule BLOCK dari alias tsb di WAN    → INI yang benar-benar memblokir traffic.
                                            (tanpa rule ini, isi alias tidak berefek!)
  3. Alias `rl_tighten_ports` (type port) → port sensitif (SSH/RDP/SMB) sasaran tighten.
  4. Rule TIGHTEN inbound  (disabled)     → blok TCP ke port sensitif; di-ON-kan DQN
                                            saat aksi 'tighten'.
  5. Rule TIGHTEN outbound (disabled)     → idem, arah keluar.

PENTING: aksi 'tighten' MEMPERKETAT port sensitif saja, BUKAN memblokir semua
trafik. Rule tighten dibatasi ke alias port `rl_tighten_ports` (default 22/3389/445)
agar mengaktifkannya tidak menjatuhkan seluruh jaringan.

Aksi DQN memakai objek di atas:
  • block_ip → tambah IP ke alias (rule #2 langsung memblokirnya)
  • tighten  → enable rule #3 & #4
  • rollback → hapus IP dari alias + disable rule tighten (un-blocking)

Semua operasi idempotent: kalau objek sudah ada (dicek via deskripsi/nama), tidak
dibuat ganda. UUID rule yang dibuat dikembalikan agar disimpan ke config.

CATATAN: endpoint mengikuti OPNsense firewall automation API
(`/api/firewall/alias/*` dan `/api/firewall/filter/*`). Perlu OPNsense yang
mendukung API tsb (bawaan versi modern). Uji pada instance nyata sebelum produksi.
"""

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from PyQt6.QtCore import QThread, pyqtSignal

# deskripsi penanda supaya idempotent + mudah dikenali di GUI OPNsense
TAG_BLOCK   = "FireSense: block rl_blocklist"
TAG_TIGHT_I = "FireSense: tighten inbound"
TAG_TIGHT_O = "FireSense: tighten outbound"

# Aksi 'tighten' memperketat port sensitif ini (SSH, RDP, SMB), bukan block-all.
TIGHTEN_PORTS_ALIAS = "rl_tighten_ports"
TIGHTEN_PORTS       = ["22", "3389", "445"]

TIMEOUT = (6, 20)


def _session(cfg):
    s = requests.Session()
    s.auth = (cfg.get("api_key"), cfg.get("api_secret"))
    s.verify = bool(cfg.get("verify_ssl"))
    return s


def _host(cfg):
    return (cfg.get("opnsense_host") or "").rstrip("/")


# ── Alias ────────────────────────────────────────────────────────────────────
def alias_exists(s, host, name):
    try:
        r = s.get(f"{host}/api/firewall/alias_util/list/{name}", timeout=TIMEOUT)
        return r.status_code == 200
    except requests.RequestException:
        return False


def reachable(s, host):
    """Quick auth+connectivity probe so we fail fast with one clear message
    instead of timing out on every create call."""
    try:
        r = s.get(f"{host}/api/core/firmware/info", timeout=TIMEOUT)
        if r.status_code == 401:
            return False, "Autentikasi gagal (401), cek API Key/Secret."
        r.raise_for_status()
        return True, ""
    except requests.exceptions.SSLError:
        return False, "Kesalahan SSL, nonaktifkan 'Verifikasi sertifikat SSL' atau pakai sertifikat valid."
    except requests.exceptions.RequestException as e:
        return False, f"Tidak bisa terhubung ke OPNsense: {e.__class__.__name__}"


def create_alias(s, host, name, desc, atype="host", content="", log=None):
    body = {"alias": {"enabled": "1", "name": name, "type": atype,
                      "content": content, "description": desc}}
    try:
        r = s.post(f"{host}/api/firewall/alias/addItem", json=body, timeout=TIMEOUT)
        data = r.json() if r.content else {}
    except (requests.RequestException, ValueError) as e:
        return False, f"{e.__class__.__name__}"
    if data.get("result") == "saved":
        try:
            s.post(f"{host}/api/firewall/alias/reconfigure", timeout=TIMEOUT)
        except requests.RequestException as e:
            if log:
                log(f"  ⚠ Alias '{name}' tersimpan tapi reconfigure gagal: {e.__class__.__name__} — muat ulang alias manual bila perlu.")
        return True, data.get("uuid", "")
    return False, str(data)


# ── Filter rules ─────────────────────────────────────────────────────────────
def find_rule_uuid(s, host, description):
    """Return uuid of an automation rule matching description, or None."""
    try:
        r = s.get(f"{host}/api/firewall/filter/searchRule",
                  params={"searchPhrase": description, "rowCount": 200}, timeout=TIMEOUT)
        rows = (r.json() or {}).get("rows", []) if r.status_code == 200 else []
        for row in rows:
            if row.get("description") == description:
                return row.get("uuid")
    except (requests.RequestException, ValueError):
        pass
    return None


def rule_exists(s, host, uuid):
    """True if a filter automation rule with this UUID still exists.
    Lets provisioning reuse a rule already referenced in config (mis. rule lab
    yang deskripsinya bukan tag FireSense) alih-alih membuat duplikat."""
    if not uuid:
        return False
    try:
        r = s.get(f"{host}/api/firewall/filter/getRule/{uuid}", timeout=TIMEOUT)
        return r.status_code == 200 and bool((r.json() or {}).get("rule"))
    except (requests.RequestException, ValueError):
        return False


def create_rule(s, host, fields):
    try:
        r = s.post(f"{host}/api/firewall/filter/addRule", json={"rule": fields}, timeout=TIMEOUT)
        data = r.json() if r.content else {}
    except (requests.RequestException, ValueError) as e:
        return False, f"{e.__class__.__name__}"
    if data.get("result") == "saved":
        return True, data.get("uuid", "")
    return False, str(data)


def apply_filter(s, host):
    """Terapkan perubahan filter yang tertunda. Return (ok, msg)."""
    try:
        s.post(f"{host}/api/firewall/filter/apply", timeout=TIMEOUT)
        return True, ""
    except requests.RequestException as e:
        return False, e.__class__.__name__


def _block_rule_fields(alias, wan_if):
    return {
        "enabled": "1", "action": "block", "quick": "1",
        "interface": wan_if, "direction": "in",
        "ipprotocol": "inet", "protocol": "any",
        "source_net": alias, "destination_net": "any",
        "log": "1", "description": TAG_BLOCK,
    }


def _tighten_inbound_fields(wan_if, ports_alias=TIGHTEN_PORTS_ALIAS):
    # Rule ketat: blok inbound TCP ke PORT SENSITIF saja (alias rl_tighten_ports),
    # bukan seluruh trafik. Dibuat DISABLED — DQN meng-ON-kan saat aksi 'tighten'.
    return {
        "enabled": "0", "action": "block", "quick": "1",
        "interface": wan_if, "direction": "in",
        "ipprotocol": "inet", "protocol": "TCP",
        "source_net": "any", "destination_net": "any",
        "destination_port": ports_alias,
        "log": "1", "description": TAG_TIGHT_I,
    }


def _tighten_outbound_fields(wan_if, ports_alias=TIGHTEN_PORTS_ALIAS):
    # Idem, arah keluar: blok TCP menuju port sensitif (batasi lateral movement /
    # exfiltrasi ke layanan tsb), bukan memblokir semua outbound.
    return {
        "enabled": "0", "action": "block", "quick": "1",
        "interface": wan_if, "direction": "out",
        "ipprotocol": "inet", "protocol": "TCP",
        "source_net": "any", "destination_net": "any",
        "destination_port": ports_alias,
        "log": "1", "description": TAG_TIGHT_O,
    }


# ── Orchestration ────────────────────────────────────────────────────────────
def provision_all(cfg, log, wan_if="wan"):
    """Create alias + block rule + tighten rules if missing.
    `log` is a callable(str). Returns a result dict."""
    host = _host(cfg)
    alias = cfg.get("blocklist_alias") or "rl_blocklist"
    s = _session(cfg)
    result = {"ok": True, "alias": alias, "block_uuid": "",
              "tighten_inbound": "", "tighten_outbound": "", "errors": []}

    if not host or not cfg.get("api_key") or not cfg.get("api_secret"):
        log("✖ Koneksi belum dikonfigurasi (host/API key). Isi & simpan Pengaturan dulu.")
        result["ok"] = False
        result["errors"].append("connection not configured")
        return result

    # 0) Fail fast if OPNsense is unreachable / auth invalid
    log("• Menguji koneksi ke OPNsense…")
    ok, msg = reachable(s, host)
    if not ok:
        log(f"  ✖ {msg}")
        result["ok"] = False; result["errors"].append("unreachable")
        return result
    log("  ✔ Terhubung.")

    # 1) Alias
    log(f"• Memeriksa alias '{alias}'…")
    if alias_exists(s, host, alias):
        log(f"  ✔ Alias '{alias}' sudah ada.")
    else:
        ok, info = create_alias(s, host, alias, "FireSense DQN dynamic blocklist", log=log)
        if ok:
            log(f"  ✔ Alias '{alias}' dibuat.")
        else:
            log(f"  ✖ Gagal membuat alias: {info}")
            result["ok"] = False; result["errors"].append("alias")

    # 2) Block rule (the one that actually enforces the blocklist)
    log("• Memeriksa rule BLOCK dari alias di WAN…")
    uuid = find_rule_uuid(s, host, TAG_BLOCK)
    if uuid:
        log("  ✔ Rule block sudah ada."); result["block_uuid"] = uuid
    else:
        ok, info = create_rule(s, host, _block_rule_fields(alias, wan_if))
        if ok:
            log("  ✔ Rule block dibuat (memblokir semua IP di alias)."); result["block_uuid"] = info
        else:
            log(f"  ✖ Gagal membuat rule block: {info}")
            result["ok"] = False; result["errors"].append("block_rule")

    # 3) Port alias for tighten rules (so 'tighten' scopes to sensitive ports,
    #    not block-all). Non-fatal: if it fails, tighten rules below will warn.
    log(f"• Memeriksa alias port '{TIGHTEN_PORTS_ALIAS}' ({', '.join(TIGHTEN_PORTS)})…")
    if alias_exists(s, host, TIGHTEN_PORTS_ALIAS):
        log(f"  ✔ Alias port '{TIGHTEN_PORTS_ALIAS}' sudah ada.")
    else:
        ok, info = create_alias(
            s, host, TIGHTEN_PORTS_ALIAS,
            "FireSense tighten sensitive ports (SSH/RDP/SMB)",
            atype="port", content="\n".join(TIGHTEN_PORTS), log=log)
        if ok:
            log(f"  ✔ Alias port '{TIGHTEN_PORTS_ALIAS}' dibuat.")
        else:
            log(f"  ⚠ Gagal membuat alias port: {info}")
            result["errors"].append("tighten_ports_alias")

    # 4) Tighten inbound — reuse UUID yg sudah ada di config (kalau rule-nya masih
    #    ada di OPNsense) supaya rule lab yg sudah terkonfigurasi tidak diduplikasi;
    #    jika tidak, cari via tag; jika tetap tidak ada, buat rule ter-scope baru.
    log("• Memeriksa rule TIGHTEN inbound (nonaktif)…")
    cfg_in = cfg.get("rule_tighten_inbound")
    uuid = cfg_in if rule_exists(s, host, cfg_in) else find_rule_uuid(s, host, TAG_TIGHT_I)
    if uuid:
        log("  ✔ Rule tighten inbound sudah ada."); result["tighten_inbound"] = uuid
    else:
        ok, info = create_rule(s, host, _tighten_inbound_fields(wan_if))
        if ok:
            log("  ✔ Rule tighten inbound dibuat (nonaktif, port sensitif)."); result["tighten_inbound"] = info
        else:
            log(f"  ⚠ Gagal membuat rule tighten inbound: {info}")
            result["errors"].append("tighten_inbound")

    # 5) Tighten outbound — idem
    log("• Memeriksa rule TIGHTEN outbound (nonaktif)…")
    cfg_out = cfg.get("rule_tighten_outbound")
    uuid = cfg_out if rule_exists(s, host, cfg_out) else find_rule_uuid(s, host, TAG_TIGHT_O)
    if uuid:
        log("  ✔ Rule tighten outbound sudah ada."); result["tighten_outbound"] = uuid
    else:
        ok, info = create_rule(s, host, _tighten_outbound_fields(wan_if))
        if ok:
            log("  ✔ Rule tighten outbound dibuat (nonaktif, port sensitif)."); result["tighten_outbound"] = info
        else:
            log(f"  ⚠ Gagal membuat rule tighten outbound: {info}")
            result["errors"].append("tighten_outbound")

    log("• Menerapkan konfigurasi firewall (apply)…")
    ok, info = apply_filter(s, host)
    if ok:
        log("  ✔ Konfigurasi firewall diterapkan.")
    else:
        log(f"  ⚠ Gagal menerapkan konfigurasi (apply): {info} — perubahan mungkin belum aktif, jalankan Apply manual di OPNsense.")
        result["ok"] = False
        result["errors"].append("apply")

    if result["ok"]:
        log("✔ Penyiapan OPNsense otomatis selesai. Objek siap dipakai DQN.")
    else:
        log("⚠ Sebagian objek gagal dibuat, lihat pesan di atas.")
    return result


class ProvisionRunner(QThread):
    """Run provisioning on a background thread so the UI stays responsive."""
    log_line = pyqtSignal(str)
    done     = pyqtSignal(dict)

    def __init__(self, cfg, wan_if="wan", parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.wan_if = wan_if

    def run(self):
        try:
            res = provision_all(self.cfg, self.log_line.emit, self.wan_if)
        except Exception as e:
            self.log_line.emit(f"✖ Kesalahan penyiapan: {e}")
            res = {"ok": False, "errors": [str(e)]}
        self.done.emit(res)
