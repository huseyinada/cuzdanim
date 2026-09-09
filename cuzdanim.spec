# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build recipe for the Windows desktop EXE.

    pyinstaller --noconfirm --clean cuzdanim.spec      (or just run derle.bat)

One-file console EXE. Read-only assets (PWA static files, Alembic migrations)
are bundled; user data is created next to the .exe at runtime (see app/paths.py).
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

datas = [
    ("app/static", "app/static"),
    ("alembic", "alembic"),
    ("alembic.ini", "."),
    (".env.example", "."),
]
datas += collect_data_files("tzdata")          # IANA zones for zoneinfo on Windows
datas += copy_metadata("apscheduler")
datas += copy_metadata("tzdata")

hiddenimports = (
    collect_submodules("app")
    + collect_submodules("uvicorn")
    + collect_submodules("apscheduler")
    + collect_submodules("sqlalchemy.dialects.sqlite")
    + collect_submodules("alembic.ddl")
    + collect_submodules("passlib.handlers")
    + [
        "aiosqlite",
        "bcrypt",
        "pywebpush",
        "py_vapid",
        "http_ece",
        "email_validator",
        "dns.resolver",
        "jose.backends.cryptography_backend",
        "alembic.runtime.migration",
        "alembic.script",
        "alembic.operations.batch",
        "greenlet",
    ]
)

a = Analysis(
    ["run_desktop.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "asyncpg", "psycopg2", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Cuzdanim",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon="app/static/icons/cuzdanim.ico",
    version="version_info.txt",
)
