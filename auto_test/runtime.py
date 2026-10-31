"""Writable runtime paths for source runs and frozen Windows builds."""
import os
import re
import sys
from pathlib import Path


def app_directory():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


def user_data_directory():
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AutoTestHost"
    root.mkdir(parents=True, exist_ok=True)
    return root


def reports_directory():
    root = app_directory() / "test_reports"
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write_check"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError:
        root = user_data_directory() / "test_reports"
        root.mkdir(parents=True, exist_ok=True)
    return root


def safe_filename(name):
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" .") or "电源"
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", clean):
        clean = "_" + clean
    return clean[:100]


def configure_runtime(log_file=None):
    cache = str(user_data_directory() / "matplotlib")
    if getattr(sys, "frozen", False):
        os.environ["MPLCONFIGDIR"] = cache
    else:
        os.environ.setdefault("MPLCONFIGDIR", cache)
    log = Path(log_file) if log_file else user_data_directory() / "host.log"
    if log_file or sys.stdout is None or sys.stderr is None:
        log.parent.mkdir(parents=True, exist_ok=True)
        stream = log.open("w" if log_file else "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = stream
    elif hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return log
