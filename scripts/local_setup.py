"""Create .env for single-process local mode and a permanent API key (no Redis needed).

    python -m scripts.local_setup      -> prints the API key (also saved in secrets/api_key.txt)

The key is stored only as an HMAC hash in API_KEY_HASHES, so it survives restarts even
though local mode keeps everything else in memory.
"""
from __future__ import annotations

import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
KEY_FILE = ROOT / "secrets" / "api_key.txt"

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
