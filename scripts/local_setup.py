"""Create .env for single-process local mode and a permanent API key (no Redis needed).

    python -m scripts.local_setup               -> prints the API key (also saved in secrets/api_key.txt)
    python -m scripts.local_setup --rotate-key  -> replaces the key (the old one stops working at the next start)

The key is stored only as an HMAC hash in API_KEY_HASHES, so it survives restarts even
though local mode keeps everything else in memory.
"""
from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
KEY_FILE = ROOT / "secrets" / "api_key.txt"
# Only the hosted dashboard may call the API from a browser (plus pages on this computer).
# The key is still required; this just stops other websites from using it in a visitor's browser.
DASHBOARD_ORIGINS = "https://heatmapify.onrender.com,https://heatmapify.netlify.app"

LOCAL_OVERRIDES = {
    "REDIS_URL": "memory://",
    "WEB_CONCURRENCY": "1",
    "WORKER_CONCURRENCY": "1",
    "GLOBAL_MAX_JOBS": "1",
    "TMP_DIR": "./tmp",
}


def _set(text: str, key: str, value: str) -> str:
    line = f"{key}={value}"
    pat = re.compile(rf"^{key}=.*$", re.M)
    return pat.sub(lambda _: line, text) if pat.search(text) else text.rstrip("\n") + "\n" + line + "\n"


def main() -> None:
    if not ENV.exists():
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        text = _set(text, "API_KEY_PEPPER", secrets.token_urlsafe(36))
        for k, v in LOCAL_OVERRIDES.items():
            text = _set(text, k, v)
        ENV.write_text(text, encoding="utf-8")

    # Older versions set CORS_ORIGINS=* (any website). Narrow that, and an empty value, to the
    # dashboard. Origins the user chose themselves are kept.
    text = ENV.read_text(encoding="utf-8")
    m = re.search(r"^CORS_ORIGINS=[ \t]*([^#\n]*)", text, re.M)
    if not m or m.group(1).strip() in ("", "*"):
        ENV.write_text(_set(text, "CORS_ORIGINS", DASHBOARD_ORIGINS), encoding="utf-8")

    if "--rotate-key" in sys.argv[1:] and KEY_FILE.exists():
        from app.auth import hash_key
        from app.config import get_settings

        get_settings.cache_clear()
        old = hash_key(KEY_FILE.read_text(encoding="utf-8").strip())
        text = ENV.read_text(encoding="utf-8")
        m = re.search(r"^API_KEY_HASHES=([^#\n]*)", text, re.M)
        kept = [x.strip() for x in (m.group(1) if m else "").split(",") if x.strip() and x.strip().lower() != old]
        ENV.write_text(_set(text, "API_KEY_HASHES", ",".join(kept)), encoding="utf-8")
        KEY_FILE.unlink()

    if not KEY_FILE.exists():
        from app.auth import generate_key, hash_key
        from app.config import get_settings

        get_settings.cache_clear()
        raw = generate_key()
        text = ENV.read_text(encoding="utf-8")
        m = re.search(r"^API_KEY_HASHES=([^#\n]*)", text, re.M)
        existing = [x.strip() for x in (m.group(1) if m else "").split(",") if x.strip()]
        text = _set(text, "API_KEY_HASHES", ",".join(existing + [hash_key(raw)]))
        ENV.write_text(text, encoding="utf-8")
        KEY_FILE.parent.mkdir(exist_ok=True)
        KEY_FILE.write_text(raw + "\n", encoding="utf-8")

    print(KEY_FILE.read_text(encoding="utf-8").strip())


if __name__ == "__main__":
    main()
