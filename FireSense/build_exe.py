"""
build_exe.py — Build the FireSense Windows .exe with PyInstaller (Python driver).

This is the Python equivalent of build.bat: it produces the SAME bundle
(--onedir, --windowed, icon, model + scaler + assets embedded) so you can test
the packaged application exactly as it will ship.

USAGE (run from inside the `firesense/` folder, on Windows, after `pip install`
of the deps — PyQt6 pyqtgraph tensorflow numpy pandas scikit-learn scipy
requests joblib pyinstaller):

    python build_exe.py            # build the .exe (full logs streamed)
    python build_exe.py --run      # just launch the app (fast test, no build)
    python build_exe.py --clean    # remove previous build/ dist/ output first

Output:
    dist/FireSense/FireSense.exe   ← double-click to test

Notes
-----
• The DQN model + scaler are pulled from the project root (../checkpoints and
  ../scaler.pkl) and embedded into the bundle, matching the deploy setup.
• Only the *.py files of FireSenseCli are bundled (never the venv), so the
  build stays small — the script stages them into a temp folder for that.
"""

import os
import sys
import shutil
import subprocess
import tempfile

# ── Locations ────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))          # .../firesense
ROOT = os.path.dirname(HERE)                               # project root (TA)
SEP  = os.pathsep                                          # ';' on Windows, ':' elsewhere

APP_NAME    = "FireSense"
ENTRY       = os.path.join(HERE, "main.py")
ICON        = os.path.join(HERE, "assets", "icon.ico")
MODEL_SRC   = os.path.join(ROOT, "checkpoints", "dqn_final.weights.h5")
SCALER_SRC  = os.path.join(ROOT, "scaler.pkl")
AF_SRC      = os.path.join(ROOT, "FireSenseCli")

DIST   = os.path.join(HERE, "dist")
WORK   = os.path.join(HERE, "build")
SPEC   = os.path.join(HERE, "build")


# ── Helpers ──────────────────────────────────────────────────────────────────
def log(msg):
    print(f"[build] {msg}", flush=True)


def fail(msg):
    print(f"\n[ERROR] {msg}\n", flush=True)
    sys.exit(1)


def check_prereqs():
    log("Memeriksa prasyarat…")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        fail("PyInstaller belum terpasang. Jalankan:\n"
             "  pip install pyinstaller")
    missing = []
    for name in ("PyQt6", "pyqtgraph", "tensorflow", "numpy", "pandas",
                 "sklearn", "scipy", "requests", "joblib"):
        try:
            __import__(name)
        except ImportError:
            missing.append("scikit-learn" if name == "sklearn" else name)
    if missing:
        fail("Dependency belum lengkap: " + ", ".join(missing) + "\n"
             "  pip install " + " ".join(missing))
    if not os.path.exists(ICON):
        fail(f"Icon tidak ditemukan: {ICON}")
    if not os.path.exists(MODEL_SRC):
        fail(f"Model tidak ditemukan: {MODEL_SRC}\n"
             "  Pastikan checkpoints/dqn_final.weights.h5 ada di root proyek.")
    if not os.path.exists(SCALER_SRC):
        fail(f"Scaler tidak ditemukan: {SCALER_SRC}")
    log("Semua prasyarat OK.")


def stage_data(tmp):
    """Copy the data that needs filtering (model, scaler, af *.py) into a temp
    staging folder so we never bundle the venv or stray files."""
    log("Menyiapkan data (model, scaler, FireSenseCli)…")

    ckpt_dir = os.path.join(tmp, "checkpoints")
    os.makedirs(ckpt_dir, exist_ok=True)
    shutil.copy2(MODEL_SRC, os.path.join(ckpt_dir, os.path.basename(MODEL_SRC)))
    log(f"  model  -> {ckpt_dir}")

    scaler_dst = os.path.join(tmp, "scaler.pkl")
    shutil.copy2(SCALER_SRC, scaler_dst)
    log(f"  scaler -> {scaler_dst}")

    af_dir = os.path.join(tmp, "FireSenseCli")
    os.makedirs(af_dir, exist_ok=True)
    n = 0
    for fn in os.listdir(AF_SRC):
        if fn.endswith(".py"):
            shutil.copy2(os.path.join(AF_SRC, fn), os.path.join(af_dir, fn))
            n += 1
    log(f"  FireSenseCli -> {n} file .py")
    return ckpt_dir, scaler_dst, af_dir


def build():
    check_prereqs()
    tmp = tempfile.mkdtemp(prefix="firesense_build_")
    try:
        ckpt_dir, scaler_dst, af_dir = stage_data(tmp)

        add_data = [
            f"{os.path.join(HERE, 'assets')}{SEP}assets",
            f"{os.path.join(HERE, 'ui')}{SEP}ui",
            f"{af_dir}{SEP}FireSenseCli",
            f"{ckpt_dir}{SEP}checkpoints",
            f"{scaler_dst}{SEP}.",
        ]
        hidden = [
            "PyQt6.sip", "PyQt6.QtSvg",
            "config_manager", "stages", "worker", "provision",
            "ui", "ui.main_window", "ui.styles",
            "pyqtgraph", "tensorflow", "sklearn",
            "sklearn.utils._cython_blas", "sklearn.neighbors._typedefs",
            "sklearn.neighbors._quad_tree", "sklearn.tree._utils",
            "scipy.ndimage",
        ]

        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onedir", "--windowed", "--noconfirm",
            "--name", APP_NAME,
            "--icon", ICON,
            "--paths", HERE,
            "--distpath", DIST,
            "--workpath", WORK,
            "--specpath", SPEC,
            "--collect-all", "pyqtgraph",
            "--collect-all", "tensorflow",
        ]
        for d in add_data:
            cmd += ["--add-data", d]
        for h in hidden:
            cmd += ["--hidden-import", h]
        cmd.append(ENTRY)

        log("Menjalankan PyInstaller (bisa 5–15 menit, log lengkap di bawah)…")
        print("-" * 70, flush=True)
        # stream PyInstaller output live so every stage is visible
        result = subprocess.run(cmd, cwd=HERE)
        print("-" * 70, flush=True)
        if result.returncode != 0:
            fail(f"PyInstaller gagal (exit {result.returncode}). Lihat log di atas.")

        exe = os.path.join(DIST, APP_NAME, f"{APP_NAME}.exe"
                           if os.name == "nt" else APP_NAME)
        log("BUILD BERHASIL ✔")
        log(f"Aplikasi : {os.path.join(DIST, APP_NAME)}")
        log(f"Jalankan : {exe}")
        if os.name == "nt":
            log("Tip: double-click FireSense.exe untuk testing. Jika ikon lama "
                "masih muncul, jalankan `ie4uinit.exe -ClearIconCache`.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_app():
    """Launch the app directly (no packaging) for a quick functional test."""
    log("Menjalankan FireSense langsung (mode dev)…")
    env = dict(os.environ)
    sys.path.insert(0, HERE)
    sys.path.insert(0, AF_SRC)
    subprocess.run([sys.executable, ENTRY], cwd=HERE, env=env)


def clean():
    for p in (DIST, WORK):
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
            log(f"Dihapus: {p}")


if __name__ == "__main__":
    args = set(sys.argv[1:])
    if "--run" in args:
        run_app()
    else:
        if "--clean" in args:
            clean()
        build()
