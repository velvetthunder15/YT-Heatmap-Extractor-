"""Manage API keys stored (hashed) in Redis.

  python -m scripts.manage_keys create --name alice --rate 60 --quota 1000
  python -m scripts.manage_keys list
  python -m scripts.manage_keys revoke <key_hash>
  python -m scripts.manage_keys hash <raw_key>     # for API_KEY_HASHES
"""
from __future__ import annotations

import argparse
import json

from app.auth import create_key, hash_key, revoke_key
from app.cache import get_redis


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--name", required=True)
    c.add_argument("--rate", type=int, help="requests per minute")
    c.add_argument("--quota", type=int, help="requests per day")
    sub.add_parser("list")
    rv = sub.add_parser("revoke")
    rv.add_argument("key_hash")
    h = sub.add_parser("hash")
    h.add_argument("raw_key")
    a = ap.parse_args()

    if a.cmd == "hash":
        print(hash_key(a.raw_key))
        return
    r = get_redis()
    if a.cmd == "create":
        raw = create_key(r, a.name, a.rate, a.quota)
        print("API key (shown once, store it safely):")
        print(raw)
        print("hash:", hash_key(raw))
    elif a.cmd == "list":
        for k in r.scan_iter("apikey:*"):
            print(k.decode().split(":", 1)[1], json.loads(r.get(k)))
    elif a.cmd == "revoke":
        print("revoked" if revoke_key(r, a.key_hash) else "not found")


if __name__ == "__main__":
    main()
