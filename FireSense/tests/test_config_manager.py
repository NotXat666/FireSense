"""Unit tests for config_manager — defaults, path resolution, ocfg patching."""
import os
import pytest

import config_manager as cm


def test_new_defaults_present(tmp_config_home):
    c = cm.ConfigManager()
    # keys added while hardening the deployment must exist with sane defaults
    assert c.get("wan_if") == "wan"
    assert c.get("wan_phys_if") == "em0"
    assert c.get("latency_warn_ms") == 1200
    assert "scaler_path" in c.data


def test_save_load_roundtrip(tmp_config_home):
    c = cm.ConfigManager()
    c.set("opnsense_host", "https://10.0.0.1:8443")
    c.set("wan_phys_if", "igb0")
    c.save()

    c2 = cm.ConfigManager()          # fresh load from the same temp file
    assert c2.get("opnsense_host") == "https://10.0.0.1:8443"
    assert c2.get("wan_phys_if") == "igb0"


def test_blank_paths_fall_back_to_bundled(tmp_config_home):
    c = cm.ConfigManager()
    c.set("model_path", "")
    c.set("scaler_path", "")
    # blank → resolver returns *some* path (bundled default or ocfg fallback),
    # never the empty string
    assert c.model_path()
    assert c.scaler_path()


def test_explicit_paths_win(tmp_config_home, tmp_path):
    c = cm.ConfigManager()
    fake_model = tmp_path / "my.h5"; fake_model.write_text("x")
    c.set("model_path", str(fake_model))
    assert c.model_path() == str(fake_model)


def test_apply_to_ocfg_patches_wan_and_own_ips(tmp_config_home):
    import opnsense_config as ocfg
    c = cm.ConfigManager()
    c.set("wan_ip", "192.168.9.4")
    c.set("wan_if", "opt1")
    c.set("wan_phys_if", "igb2")
    c.set("api_key", "K"); c.set("api_secret", "S")
    c.apply_to_ocfg()

    assert ocfg.WAN_IF == "opt1"
    assert ocfg.WAN_PHYS_IF == "igb2"
    assert "192.168.9.4" in ocfg.OWN_IPS
    assert ocfg.API_KEY == "K" and ocfg.API_SECRET == "S"


def test_apply_to_ocfg_only_includes_provided_rule_uuids(tmp_config_home):
    import opnsense_config as ocfg
    c = cm.ConfigManager()
    c.set("rule_tighten_inbound", "uuid-in")
    c.set("rule_tighten_outbound", "")   # blank → excluded
    c.apply_to_ocfg()
    assert ocfg.RULE_UUIDS.get("tighten_inbound") == "uuid-in"
    assert "tighten_outbound" not in ocfg.RULE_UUIDS
