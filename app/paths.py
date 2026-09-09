"""
Where things live — works both from source and inside a PyInstaller one-file EXE.

    BUNDLE_DIR  read-only assets shipped with the code (static/, alembic/, alembic.ini).
                Frozen: the temp extraction dir (sys._MEIPASS). Source: project root.
    DATA_DIR    user data that must persist (finance_tracker.db, backups/, .env,
                vapid_keys.json). Frozen: the folder the .exe sits in. Source: project root.

The desktop launcher `chdir`s into DATA_DIR before importing the app, so every
relative path in settings (DATABASE_URL, VAPID_KEYS_FILE, .env) resolves there.
"""
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
_SOURCE_ROOT = Path(__file__).resolve().parents[1]

BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", _SOURCE_ROOT))
DATA_DIR = Path(sys.executable).resolve().parent if FROZEN else _SOURCE_ROOT
