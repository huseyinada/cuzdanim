"""
Desktop launcher — entry point of the PyInstaller build (Cüzdanım.exe).

Double-click behaviour:
    1. Uses the folder the .exe sits in as the data folder (database, backups,
       .env, push keys) so nothing is lost between runs or updates.
    2. Creates a `.env` with a strong random SECRET_KEY on first start.
    3. Starts the API + PWA on port 8000 (or $PORT), prints the LAN address
       for the phone, and opens the browser.
Also runnable from source: `python run_desktop.py`.
"""
import os
import secrets
import socket
import sys
import threading
import webbrowser
from pathlib import Path


def _data_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "PC-IP-ADRESI"


def _ensure_env(data_dir: Path) -> None:
    env = data_dir / ".env"
    if env.exists():
        return
    env.write_text(
        "\n".join(
            [
                "# Cüzdanım — otomatik oluşturuldu. Değerleri değiştirip uygulamayı yeniden başlatabilirsin.",
                f"SECRET_KEY={secrets.token_urlsafe(48)}",
                "ENVIRONMENT=production",
                "DATABASE_URL=sqlite+aiosqlite:///./finance_tracker.db",
                "SCHEDULER_TIMEZONE=Europe/Istanbul",
                "DAILY_MESSAGE_HOUR=8",
                "BUDGET_CHECK_HOUR=20",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # pragma: no cover
            pass

    data_dir = _data_dir()
    os.chdir(data_dir)  # all relative paths (db, backups, .env, vapid keys) live next to the exe
    _ensure_env(data_dir)

    import uvicorn

    from app.config import settings
    from app.main import app

    port = int(os.environ.get("PORT", "8000"))
    ip = _lan_ip()
    print("=" * 50)
    print(f"  {settings.APP_NAME} v{settings.APP_VERSION}")
    print("=" * 50)
    print(f"  Veri klasörü:   {data_dir}")
    print(f"  PC'de aç:       http://localhost:{port}")
    print(f"  Telefondan aç:  http://{ip}:{port}   (aynı Wi-Fi)")
    print(f"  API dokümanı:   http://localhost:{port}/docs")
    print("  Kapatmak için bu pencereyi kapat veya Ctrl+C.")
    print("-" * 50)

    if os.environ.get("CUZDANIM_NO_BROWSER") != "1":  # set to 1 for headless/autostart use
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
