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


def _remote_url(data_dir: Path) -> str | None:
    """Read the optional `sunucu.txt` next to the exe.

    If it contains a real http(s) URL, the launcher stops running its own
    local server + database and instead just opens that URL — i.e. it turns
    into a shortcut to the always-on cloud server (Render). Delete the file,
    or blank it out, to go back to local mode. No rebuild needed either way.
    """
    f = data_dir / "sunucu.txt"
    if not f.exists():
        f.write_text(
            "\n".join(
                [
                    "# Bu dosyaya bulut sunucunun adresini yazarsan (ör. https://cuzdanim.onrender.com),",
                    "# Cüzdanım.exe kendi yerel sunucusunu başlatmak yerine doğrudan o adrese bağlanır.",
                    "# Boş/# ile başlayan satırlar yok sayılır. Yerel moda dönmek için bu dosyayı boşalt.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return None
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line.startswith(("http://", "https://")):
            return line.rstrip("/")
    return None


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

    remote = _remote_url(data_dir)
    if remote:
        print("=" * 50)
        print("  Cüzdanım — bulut sunucusuna bağlanılıyor")
        print("=" * 50)
        print(f"  Sunucu:  {remote}")
        print("  Bu pencere sadece bir kısayoldur, veriler bu bilgisayarda tutulmaz;")
        print("  hepsi bulut sunucusunda ve her cihazda aynı görünür.")
        print(f"  Yerel moda dönmek için: {data_dir / 'sunucu.txt'} dosyasını boşalt.")
        print("-" * 50)
        webbrowser.open(remote)
        if os.environ.get("CUZDANIM_NO_BROWSER") != "1":
            try:
                input("Kapatmak için Enter'a bas...")
            except (EOFError, KeyboardInterrupt):
                pass
        return

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
