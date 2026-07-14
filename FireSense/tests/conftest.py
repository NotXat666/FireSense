"""Shared pytest fixtures for FireSense unit tests.

These tests are deliberately light: no TensorFlow, no network, no real OPNsense.
They exercise the pure-Python glue (config resolution, actuator action routing,
worker connectivity de-dup) that the deployment correctness depends on.
"""
import os
import sys
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIRESENSE = os.path.dirname(_HERE)
_REPO = os.path.dirname(_FIRESENSE)
_AF = os.path.join(_REPO, "FireSenseCli")

for p in (_FIRESENSE, _AF):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def tmp_config_home(tmp_path, monkeypatch):
    """Redirect the per-user config dir into a temp folder so tests never read
    or clobber the developer's real ~/.config/firesense/config.json."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    return tmp_path
