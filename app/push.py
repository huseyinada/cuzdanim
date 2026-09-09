"""
Web Push plumbing: VAPID key management + a single blocking send helper.

Keys resolve in this order:
    1. `VAPID_PRIVATE_KEY` + `VAPID_PUBLIC_KEY` env vars (recommended for
       ephemeral hosts like Render/Fly so subscriptions survive redeploys).
    2. `VAPID_KEYS_FILE` on disk (auto-created on first start for local use).

`send_web_push` is synchronous (pywebpush uses `requests`); callers in the
async world run it via `asyncio.to_thread`.
"""
import base64
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

from app.config import settings

logger = logging.getLogger("app.push")


@dataclass(frozen=True)
class VapidKeys:
    private_pem: str
    public_key: str  # base64url, raw uncompressed EC point — what the browser needs


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_vapid_keys() -> VapidKeys:
    """Generate a P-256 key pair directly with `cryptography`.

    (py-vapid's own `generate_keys()` passes the curve *class* instead of an
    instance and breaks on current cryptography releases; pywebpush still
    happily consumes the PEM we produce here.)
    """
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    public_key = _b64url(
        private_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )
    return VapidKeys(private_pem=private_pem, public_key=public_key)


@lru_cache
def get_vapid_keys() -> VapidKeys:
    if settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY:
        # Allow "\n"-escaped single-line PEM in env files.
        return VapidKeys(
            private_pem=settings.VAPID_PRIVATE_KEY.replace("\\n", "\n"),
            public_key=settings.VAPID_PUBLIC_KEY,
        )

    path = Path(settings.VAPID_KEYS_FILE)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return VapidKeys(private_pem=data["private_pem"], public_key=data["public_key"])

    keys = generate_vapid_keys()
    path.write_text(
        json.dumps({"private_pem": keys.private_pem, "public_key": keys.public_key}, indent=2),
        encoding="utf-8",
    )
    logger.warning(
        "Generated new VAPID keys into %s. On cloud hosts set VAPID_PRIVATE_KEY / "
        "VAPID_PUBLIC_KEY env vars instead (python -m app.tools.vapid prints them).",
        path,
    )
    return keys


@lru_cache
def get_vapid_signer() -> Vapid:
    """A py_vapid `Vapid` built from our PEM.

    pywebpush accepts either a `Vapid` instance or a *base64 raw/DER* string —
    handing it PEM text makes it base64-decode the PEM and fail with an ASN.1
    error, so we always pass the instance.
    """
    private_key = serialization.load_pem_private_key(
        get_vapid_keys().private_pem.encode("utf-8"), password=None
    )
    return Vapid(private_key)


def send_web_push(
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    payload: dict,
    ttl: int = 86400,
) -> tuple[bool, bool, Optional[int]]:
    """Deliver one push message.

    Returns `(ok, stale, status_code)` — `stale=True` means the push service
    reported the subscription is gone (404/410) and the row should be deleted.
    """
    try:
        webpush(
            subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=get_vapid_signer(),
            vapid_claims={"sub": settings.VAPID_CLAIMS_EMAIL},  # fresh dict: pywebpush mutates it
            ttl=ttl,
            timeout=10,
        )
        return True, False, 201
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        stale = status in (404, 410)
        logger.warning("Web push failed (status=%s, stale=%s): %s", status, stale, exc)
        return False, stale, status
    except Exception as exc:  # network errors etc. — never let one device break the batch
        logger.warning("Web push raised unexpectedly: %s", exc)
        return False, False, None
