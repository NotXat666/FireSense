"""Unit + integration tests for provision.py — OPNsense auto-setup, no network.

All HTTP is stubbed with a FakeSession (routed by URL), so these verify the
local logic: reachability messages, rule/alias field shapes, idempotent reuse,
and — crucially — that apply/reconfigure failures are now *surfaced* (logged /
flagged) instead of being swallowed silently.
"""
import json
import pytest
import requests

import provision as pv


# ── Fake HTTP plumbing ───────────────────────────────────────────────────────
class FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.content = json.dumps(self._payload).encode() if payload is not None else b""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class FakeSession:
    """Routes OPNsense endpoints by URL substring. Configurable to simulate
    missing objects (→ create path) and apply/reconfigure failures."""
    def __init__(self, alias_exists=False, rule_found=False, apply_fails=False):
        self.alias_exists = alias_exists
        self.rule_found = rule_found
        self.apply_fails = apply_fails
        self.calls = []          # every (verb, url) for assertions

    def get(self, url, params=None, **k):
        self.calls.append(("GET", url))
        if "firmware/info" in url:
            return FakeResp(200, {"product": "OPNsense"})
        if "alias_util/list" in url:
            return FakeResp(200 if self.alias_exists else 404,
                            {"rows": []} if self.alias_exists else {})
        if "searchRule" in url:
            # find_rule_uuid matches on description == searchPhrase, so echo it back
            phrase = (params or {}).get("searchPhrase")
            rows = [{"uuid": "existing-uuid", "description": phrase}] \
                if self.rule_found else []
            return FakeResp(200, {"rows": rows})
        if "getRule" in url:
            return FakeResp(200, {"rule": {"enabled": "0"}})
        return FakeResp(404, {})

    def post(self, url, json=None, **k):
        self.calls.append(("POST", url))
        if "alias/addItem" in url:
            return FakeResp(200, {"result": "saved", "uuid": "alias-uuid"})
        if "alias/reconfigure" in url:
            return FakeResp(200, {"status": "ok"})
        if "filter/addRule" in url:
            return FakeResp(200, {"result": "saved", "uuid": "rule-uuid"})
        if "filter/apply" in url:
            if self.apply_fails:
                raise requests.ConnectionError("apply down")
            return FakeResp(200, {"status": "ok"})
        return FakeResp(404, {})


CFG = {
    "opnsense_host": "https://10.0.0.1:8443",
    "api_key": "K", "api_secret": "S", "verify_ssl": False,
    "blocklist_alias": "rl_blocklist",
}


# ── Pure helpers ─────────────────────────────────────────────────────────────
def test_host_strips_trailing_slash():
    assert pv._host({"opnsense_host": "https://x:8443/"}) == "https://x:8443"
    assert pv._host({"opnsense_host": ""}) == ""
    assert pv._host({}) == ""


def test_reachable_maps_401_to_auth_message():
    class S:
        def get(self, *a, **k): return FakeResp(401)
    ok, msg = pv.reachable(S(), "https://x")
    assert ok is False and "401" in msg


def test_reachable_ok_on_200():
    class S:
        def get(self, *a, **k): return FakeResp(200, {})
    ok, msg = pv.reachable(S(), "https://x")
    assert ok is True and msg == ""


def test_reachable_connection_error():
    class S:
        def get(self, *a, **k): raise requests.ConnectionError("no route")
    ok, msg = pv.reachable(S(), "https://x")
    assert ok is False and msg


# ── Rule/alias field shapes (the scoping fix — tighten must NOT be block-all) ─
def test_block_rule_fields_enforce_from_alias():
    f = pv._block_rule_fields("rl_blocklist", "wan")
    assert f["enabled"] == "1" and f["action"] == "block"
    assert f["source_net"] == "rl_blocklist"
    assert f["interface"] == "wan"


def test_tighten_inbound_scoped_to_sensitive_ports_and_disabled():
    f = pv._tighten_inbound_fields("wan")
    assert f["enabled"] == "0"                          # DQN toggles it on
    assert f["protocol"] == "TCP"                       # not "any"
    assert f["destination_port"] == pv.TIGHTEN_PORTS_ALIAS
    assert f["direction"] == "in"


def test_tighten_outbound_scoped_and_outbound():
    f = pv._tighten_outbound_fields("wan")
    assert f["direction"] == "out"
    assert f["destination_port"] == pv.TIGHTEN_PORTS_ALIAS
    assert f["protocol"] == "TCP"


# ── apply_filter / create_alias no longer swallow errors (finding #2) ────────
def test_apply_filter_returns_status():
    assert pv.apply_filter(FakeSession(), "https://x") == (True, "")
    assert pv.apply_filter(FakeSession(apply_fails=True), "https://x") == (False, "ConnectionError")


def test_create_alias_logs_reconfigure_failure():
    logs = []

    class ReconfFail(FakeSession):
        def post(self, url, json=None, **k):
            if "reconfigure" in url:
                raise requests.ConnectionError("reconf down")
            return super().post(url, json=json, **k)

    ok, uuid = pv.create_alias(ReconfFail(), "https://x", "rl_test", "d", log=logs.append)
    assert ok is True and uuid == "alias-uuid"
    assert any("reconfigure gagal" in l for l in logs)   # surfaced, not silent


def test_rule_exists_false_for_blank_uuid():
    assert pv.rule_exists(FakeSession(), "https://x", "") is False


# ── provision_all integration ────────────────────────────────────────────────
def test_provision_all_creates_all_objects(monkeypatch):
    s = FakeSession(alias_exists=False, rule_found=False)
    monkeypatch.setattr(pv, "_session", lambda cfg: s)
    logs = []
    res = pv.provision_all(CFG, logs.append)

    assert res["ok"] is True
    assert res["block_uuid"] == "rule-uuid"
    assert res["tighten_inbound"] == "rule-uuid"
    assert res["tighten_outbound"] == "rule-uuid"
    assert res["errors"] == []
    # it actually issued the apply at the end
    assert ("POST", "https://10.0.0.1:8443/api/firewall/filter/apply") in s.calls


def test_provision_all_apply_failure_flags_not_ok(monkeypatch):
    s = FakeSession(alias_exists=False, rule_found=False, apply_fails=True)
    monkeypatch.setattr(pv, "_session", lambda cfg: s)
    logs = []
    res = pv.provision_all(CFG, logs.append)

    # the previously-swallowed apply failure now propagates
    assert res["ok"] is False
    assert "apply" in res["errors"]
    assert any("Gagal menerapkan" in l for l in logs)


def test_provision_all_reuses_existing_objects(monkeypatch):
    # everything already present → no create, still ok, apply still called
    s = FakeSession(alias_exists=True, rule_found=True)
    monkeypatch.setattr(pv, "_session", lambda cfg: s)
    res = pv.provision_all(CFG, lambda *_: None)

    assert res["ok"] is True
    assert res["block_uuid"] == "existing-uuid"
    # no addRule/addItem calls were made (idempotent reuse)
    assert not any("addRule" in u or "addItem" in u for _, u in s.calls)


def test_provision_all_aborts_when_unconfigured():
    res = pv.provision_all({"opnsense_host": "", "api_key": "", "api_secret": ""},
                           lambda *_: None)
    assert res["ok"] is False
    assert "connection not configured" in res["errors"]
