"""Reader-study server (Python 3.8+, standard library only).

Serves the blinded rating page to logged-in readers, stores every reader's
work on the server, and gives the investigator a results view. The server
never holds which model produced a finding (that stays in findings.json on
the investigator's machine).

Folder layout on the server (a clone of this repository, e.g. /opt/okuyucu; see README.md):
    reader_server.py  rating.html  admin.html  images640/<case>.png
    users.json      (created by --add-user; salted password hashes)
    data/           (created; rating_<reader>.json + history/)

    python3 reader_server.py --add-user O1            # prints a random password
    python3 reader_server.py --add-user admin --admin
    python3 reader_server.py --port 8443 --cert fullchain.pem --key privkey.pem

Readers open https://<host>:<port>/ ; the investigator opens /admin.
Use HTTPS (--cert/--key, or a reverse proxy such as Caddy/nginx in front of
--host 127.0.0.1): logins travel with every request.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
USERS = os.path.join(ROOT, "users.json")
DATA = os.path.join(ROOT, "data")
CASE_RE = re.compile(r"^/images640/(R\d{4})\.png$")
MAX_BODY = 4 * 1024 * 1024
FAILS = {}  # ip -> [count, window_start], simple brute-force brake
MAX_FAILS, BLOCK_S = 10, 600
SAVE_LOCK = threading.Lock()  # saves are written one at a time (shared .tmp name, history snapshot)


def read_users():
    try:
        with open(USERS, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def pw_hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()


def add_user(name, admin):
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,20}", name), "user name: letters, digits, - or _"
    users = read_users()
    pw = secrets.token_urlsafe(9)
    salt = secrets.token_hex(16)
    users[name] = {"salt": salt, "hash": pw_hash(pw, salt), "admin": admin}
    with open(USERS, "w", encoding="utf-8") as fh:
        json.dump(users, fh, indent=1)
    print(f"user {name} ({'admin' if admin else 'reader'}) password: {pw}")


class Handler(BaseHTTPRequestHandler):
    server_version = "reader"
    timeout = 60  # drop connections that never send a request (and, with --cert, never finish TLS)

    def ip(self):
        """Client address. Behind a reverse proxy on this machine (Caddy/nginx) every connection comes
        from 127.0.0.1, so take the address the proxy appended to X-Forwarded-For (the last entry)."""
        ip = self.client_address[0]
        if ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            fwd = self.headers.get("X-Forwarded-For", "") if getattr(self, "headers", None) else ""
            ip = fwd.split(",")[-1].strip() or ip
        return ip

    def log_message(self, fmt, *args):  # no request bodies or images in the log
        print(time.strftime("%Y-%m-%d %H:%M:%S"), self.ip(), getattr(self, "user", "-"), fmt % args, flush=True)

    def send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def auth(self):
        ip, now = self.ip(), time.time()
        n, t0 = FAILS.get(ip, (0, now))
        if now - t0 >= BLOCK_S:  # window (or block) is over: count afresh
            n, t0 = 0, now
        if n >= MAX_FAILS:
            self.send(429, "Çok fazla hatalı giriş; 10 dakika sonra deneyin.".encode())
            return None
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                name, pw = base64.b64decode(h[6:]).decode().split(":", 1)
                u = read_users().get(name)
                if u and hmac.compare_digest(pw_hash(pw, u["salt"]), u["hash"]):
                    FAILS.pop(ip, None)
                    self.user = name
                    return name, u
            except Exception:
                pass
            n += 1
            FAILS[ip] = [n, now if n >= MAX_FAILS else t0]  # the 10th miss starts a full 10-minute block
        self.send(401, "Giriş gerekli".encode(), extra={"WWW-Authenticate": 'Basic realm="Okuyucu", charset="UTF-8"'})
        return None

    def file(self, name, ctype):
        with open(os.path.join(ROOT, name), "rb") as fh:
            self.send(200, fh.read(), ctype)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        who = self.auth()
        if not who:
            return
        name, u = who
        path = self.path.split("?")[0]
        if path in ("/", "/index.html", "/rating.html"):
            return self.file("rating.html", "text/html; charset=utf-8")
        m = CASE_RE.match(path)
        if m and os.path.exists(os.path.join(ROOT, "images640", m.group(1) + ".png")):
            return self.file(os.path.join("images640", m.group(1) + ".png"), "image/png")
        if path == "/api/load":
            p = os.path.join(DATA, f"rating_{name}.json")
            state = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None
            return self.send(200, json.dumps({"reader": name, "state": state}).encode(), "application/json")
        if u.get("admin") and path in ("/admin", "/admin/", "/admin.html"):
            return self.file("admin.html", "text/html; charset=utf-8")
        if u.get("admin") and path in ("/api/all", "/admin/api/all"):
            out = {}
            for f in sorted(os.listdir(DATA)):
                if f.startswith("rating_") and f.endswith(".json"):
                    p = os.path.join(DATA, f)
                    out[f[7:-5]] = {"state": json.load(open(p, encoding="utf-8")),
                                    "saved": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p)))}
            return self.send(200, json.dumps(out).encode(), "application/json")
        if u.get("admin") and CASE_RE.match(path.replace("/admin", "", 1)):
            return self.do_GET_image(path.replace("/admin", "", 1))
        self.send(404, b"not found")

    def do_GET_image(self, path):
        m = CASE_RE.match(path)
        if os.path.exists(os.path.join(ROOT, "images640", m.group(1) + ".png")):
            return self.file(os.path.join("images640", m.group(1) + ".png"), "image/png")
        self.send(404, b"not found")

    def do_POST(self):
        who = self.auth()
        if not who:
            return
        name, _ = who
        if self.path.split("?")[0] != "/api/save":
            return self.send(404, b"not found")
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 < n <= MAX_BODY:
            return self.send(413, b"too large")
        try:
            state = json.loads(self.rfile.read(n))
            assert isinstance(state, dict) and isinstance(state.get("cases", {}), dict)
        except Exception:
            return self.send(400, b"bad json")
        state["reader"] = name  # the login decides who rated, never the page
        state["saved"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        body = json.dumps(state, ensure_ascii=False, indent=1).encode("utf-8")
        p = os.path.join(DATA, f"rating_{name}.json")
        with SAVE_LOCK:
            os.makedirs(os.path.join(DATA, "history"), exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(body)
            os.replace(tmp, p)  # atomic
            # one snapshot per reader per 10 minutes, so earlier work can always be recovered
            snap = os.path.join(DATA, "history",
                                f"rating_{name}_{time.strftime('%Y%m%d_%H')}{int(time.strftime('%M')) // 10}0.json")
            with open(snap, "wb") as fh:
                fh.write(body)
        self.send(200, b'{"ok":true}', "application/json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--add-user", help="create or reset a user and print its password")
    ap.add_argument("--admin", action="store_true", help="with --add-user: may open /admin")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8443)
    ap.add_argument("--cert")
    ap.add_argument("--key")
    args = ap.parse_args()
    if args.add_user:
        return add_user(args.add_user, args.admin)
    assert read_users(), "no users yet: run with --add-user first"
    os.makedirs(DATA, exist_ok=True)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    if args.cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(args.cert, args.key)
        # handshake in the request thread (with Handler.timeout), not in accept(): otherwise one idle
        # connection, e.g. from a port scanner, would stall the whole server
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True, do_handshake_on_connect=False)
    elif args.host not in ("127.0.0.1", "localhost"):
        print("WARNING: no HTTPS. Use --cert/--key or a reverse proxy; passwords travel with every request.")
    print(f"serving {ROOT} on {'https' if args.cert else 'http'}://{args.host}:{args.port}/  (readers: /, admin: /admin)",
          flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
