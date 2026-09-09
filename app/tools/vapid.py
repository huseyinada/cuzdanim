"""Print the current VAPID keys as env-var lines for cloud deployment.

    python -m app.tools.vapid

Paste the output into your host's environment settings (Render → Environment).
"""
from app.push import get_vapid_keys


def main() -> None:
    keys = get_vapid_keys()
    print("# --- Copy these into your hosting provider's environment variables ---")
    print(f"VAPID_PUBLIC_KEY={keys.public_key}")
    # Escape newlines so the PEM fits on one line in .env / dashboard inputs.
    print("VAPID_PRIVATE_KEY=" + keys.private_pem.strip().replace("\n", "\\n"))
    print("VAPID_CLAIMS_EMAIL=mailto:you@example.com")


if __name__ == "__main__":
    main()
