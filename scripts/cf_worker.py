"""Permanent free URL on <worker>.<subdomain>.workers.dev, no domain needed.

  python -m scripts.cf_worker setup               create/refresh the Worker + KV, save settings in .env
  python -m scripts.cf_worker set-target <url>    point the Worker at the current tunnel URL
  python -m scripts.cf_worker remove              forget the Worker settings in .env

Needs a Cloudflare API token made from the "Edit Cloudflare Workers" template
(saved as CF_API_TOKEN in .env, which git ignores). Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
API = "https://api.cloudflare.com/client/v4"
WORKER_NAME = "yt-heatmap-api"
KV_TITLE = "yt-heatmap-api"
KEYS = ("CF_API_TOKEN", "CF_ACCOUNT_ID", "CF_KV_NAMESPACE_ID", "CF_WORKER_URL")


class CFError(RuntimeError):
    pass


# ---------- .env helpers ----------
def read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8-sig").splitlines():
            m = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
            if m:
                out[m.group(1)] = re.split(r"\s+#", m.group(2))[0].strip().strip('"')
    return out


def write_env(updates: dict[str, str]) -> None:
    text = ENV.read_text(encoding="utf-8-sig") if ENV.exists() else ""
    for k, v in updates.items():
        line = f"{k}={v}"
        if re.search(rf"(?m)^{k}=.*$", text):
            text = re.sub(rf"(?m)^{k}=.*$", lambda _m: line, text)
        else:
            text = text.rstrip("\r\n") + ("\n" if text else "") + line + "\n"
    ENV.write_text(text, encoding="utf-8")


# ---------- Cloudflare API ----------
def call(token: str, method: str, path: str, body=None, *, raw: bytes | None = None,
         content_type: str = "application/json", ok_codes: tuple[int, ...] = ()) -> dict:
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read().decode()
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
    try:
        payload = json.loads(txt) if txt.strip().startswith("{") else {"success": True, "result": txt}
    except ValueError:
        payload = {"success": False, "errors": [{"message": txt[:200]}]}
    if not payload.get("success", False):
        codes = {err.get("code") for err in payload.get("errors", [])}
        if codes & set(ok_codes):
            return payload
        msg = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in payload.get("errors", [])) or txt[:200]
        raise CFError(f"{method} {path} failed: {msg}")
    return payload


def put_target(token: str, account: str, ns: str, value: str) -> None:
    call(token, "PUT", f"/accounts/{account}/storage/kv/namespaces/{ns}/values/target",
         raw=value.encode(), content_type="text/plain")


def setup(token: str) -> str:
    accounts = call(token, "GET", "/accounts")["result"]
    if not accounts:
        raise CFError("This token can't see any Cloudflare account. Use the 'Edit Cloudflare Workers' template.")
    account = accounts[0]["id"]

    # workers.dev subdomain (every account picks one once)
    sub = call(token, "GET", f"/accounts/{account}/workers/subdomain", ok_codes=(10007,)).get("result") or {}
    subdomain = sub.get("subdomain") if isinstance(sub, dict) else None
    if not subdomain:
        base = re.sub(r"[^a-z0-9-]", "", accounts[0].get("name", "").split("@")[0].lower())[:20] or "heatmap"
        for cand in (base, f"{base}-{uuid.uuid4().hex[:5]}"):
            try:
                subdomain = call(token, "PUT", f"/accounts/{account}/workers/subdomain",
                                 {"subdomain": cand})["result"]["subdomain"]
                break
            except CFError:
                continue
        if not subdomain:
            raise CFError("Couldn't claim a workers.dev subdomain. Open Workers & Pages in the Cloudflare dashboard once, then retry.")

    # KV namespace (reuse if it exists)
    ns = None
    for page in range(1, 6):
        items = call(token, "GET", f"/accounts/{account}/storage/kv/namespaces?per_page=100&page={page}")["result"]
        ns = next((n["id"] for n in items if n["title"] == KV_TITLE), None)
        if ns or len(items) < 100:
            break
    if not ns:
        ns = call(token, "POST", f"/accounts/{account}/storage/kv/namespaces", {"title": KV_TITLE})["result"]["id"]

    # Upload the Worker as an ES module with the KV binding
    script = (ROOT / "worker" / "proxy.js").read_bytes()
    meta = {"main_module": "proxy.js", "compatibility_date": "2024-09-23",
            "bindings": [{"type": "kv_namespace", "name": "KV", "namespace_id": ns}]}
    boundary = "----yhx" + uuid.uuid4().hex
    parts = [
        (f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"; filename="metadata.json"\r\n'
         f"Content-Type: application/json\r\n\r\n").encode() + json.dumps(meta).encode() + b"\r\n",
        (f'--{boundary}\r\nContent-Disposition: form-data; name="proxy.js"; filename="proxy.js"\r\n'
         f"Content-Type: application/javascript+module\r\n\r\n").encode() + script + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    call(token, "PUT", f"/accounts/{account}/workers/scripts/{WORKER_NAME}", raw=b"".join(parts),
         content_type=f"multipart/form-data; boundary={boundary}")
    call(token, "POST", f"/accounts/{account}/workers/scripts/{WORKER_NAME}/subdomain",
         {"enabled": True, "previews_enabled": False})

    url = f"https://{WORKER_NAME}.{subdomain}.workers.dev"
    write_env({"CF_API_TOKEN": token, "CF_ACCOUNT_ID": account, "CF_KV_NAMESPACE_ID": ns,
               "CF_WORKER_URL": url, "PUBLIC_BASE_URL": url})
    return url


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    env = read_env()
    try:
        if cmd == "setup":
            token = (argv[2] if len(argv) > 2 else os.environ.get("CF_API_TOKEN") or env.get("CF_API_TOKEN") or "").strip()
            if not token:
                token = input("Paste your Cloudflare API token: ").strip()
            url = setup(token)
            print(url)
            return 0
        if cmd == "set-target":
            if not env.get("CF_KV_NAMESPACE_ID"):
                return 0  # not configured: nothing to do
            put_target(env["CF_API_TOKEN"], env["CF_ACCOUNT_ID"], env["CF_KV_NAMESPACE_ID"], argv[2])
            print(env.get("CF_WORKER_URL", ""))
            return 0
        if cmd == "remove":
            upd = {k: "" for k in KEYS}
            if env.get("PUBLIC_BASE_URL", "").endswith(".workers.dev"):
                upd["PUBLIC_BASE_URL"] = ""
            write_env(upd)
            print("Removed the workers.dev settings from .env.")
            return 0
    except CFError as e:
        print(f"Cloudflare error: {e}", file=sys.stderr)
        return 2
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
