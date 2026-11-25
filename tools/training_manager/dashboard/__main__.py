"""Serve or open the authenticated, loopback-only INF2 dashboard."""

import argparse
from contextlib import closing
from hashlib import sha256
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import sqlite3
import sys
from threading import Lock, Thread
from time import monotonic, sleep
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler, Request, build_opener
import webbrowser

from .backend import Backend
from .results import results
from ..common import HOME, ROOT, checksum, home_path, lease, read, write
from ..manager import Manager
from ..windows import detach


STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
PORT = 8765
MAX_JSON = 8192
DASHBOARD_ROOT = ROOT / "tools/training_manager"


def service_revision():
    paths = sorted(DASHBOARD_ROOT.rglob("*.py"))
    paths.extend(DASHBOARD_ROOT / "dashboard/static" / name for name, _ in STATIC.values())
    files = [(path.relative_to(DASHBOARD_ROOT).as_posix(), checksum(path)) for path in paths]
    return sha256(json.dumps(files).encode()).hexdigest()


class Dashboard(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, home, port):
        super().__init__(("127.0.0.1", port), Handler)
        self.backend = Backend(home)
        self.host = f"127.0.0.1:{self.server_port}"
        self.url = f"http://{self.host}"
        self.cookie = f"inf2_session_{self.server_port}"
        self.auth_lock = Lock()
        self.bootstrap = secrets.token_urlsafe(32)
        self.sessions = {}
        self.revision = service_revision()
        self.static = {route: ((DASHBOARD_ROOT / "dashboard/static" / name).read_bytes(), mime)
                       for route, (name, mime) in STATIC.items()}

    def new_session(self, proof):
        if not isinstance(proof, str) or not proof.isascii() or not secrets.compare_digest(proof, self.bootstrap):
            return None
        now = monotonic()
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.auth_lock:
            self.sessions = {k: v for k, v in self.sessions.items() if v[1] > now}
            if len(self.sessions) >= 64:
                self.sessions.pop(next(iter(self.sessions)))
            self.sessions[token] = csrf, now + 24 * 3600
        return token, csrf

    def session(self, header):
        try:
            match = SimpleCookie(header).get(self.cookie)
        except CookieError:
            return None
        if not match:
            return None
        with self.auth_lock:
            csrf, expires = self.sessions.get(match.value, (None, 0))
        return (match.value, csrf) if expires > monotonic() else None


class Handler(BaseHTTPRequestHandler):
    server_version = "INF2"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        # Paths and query strings can describe local experiment files.
        return

    def respond(self, value, code=200, mime="application/json; charset=utf-8", cookie=None):
        data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")
        if cookie:
            self.send_header("Set-Cookie", f"{self.server.cookie}={cookie}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400")
        self.end_headers()
        self.wfile.write(data)

    def host_ok(self):
        return self.headers.get_all("Host") == [self.server.host] and self.path.startswith("/") and not self.path.startswith("//")

    def session(self):
        return self.server.session(self.headers.get("Cookie", ""))

    def do_GET(self):
        if not self.host_ok():
            return self.respond({"error": "无效的本机地址"}, 403)
        path = urlsplit(self.path)
        if path.path == "/health":
            return self.respond({"service": "INF2", "instance": fingerprint(self.server.backend.home),
                                 "revision": self.server.revision})
        if path.path in self.server.static:
            content, mime = self.server.static[path.path]
            return self.respond(content, mime=mime)
        session = self.session()
        if not session or self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
            return self.respond({"error": "请从 Windows 启动器打开面板"}, 401)
        if path.path == "/api/session":
            return self.respond({"csrf": session[1]})
        backend = self.server.backend
        query = parse_qs(path.query)
        try:
            manager = Manager(backend.home)
            with closing(manager.db):
                if path.path == "/api/state":
                    payload = backend.overview(manager)
                elif path.path == "/api/plans":
                    payload = backend.plans(manager)
                elif path.path == "/api/resources":
                    payload = backend.probe()
                elif path.path == "/api/results":
                    payload = results(backend, manager)
                elif path.path == "/api/job":
                    payload = backend.details(manager, query["id"][0])
                elif path.path == "/api/file":
                    payload = backend.artifact(manager, query["id"][0], query["name"][0])
                else:
                    return self.respond({"error": "页面不存在"}, 404)
            self.respond(payload)
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
            self.respond({"error": str(error)}, 409)

    def do_POST(self):
        if (not self.host_ok() or self.headers.get_all("Origin") != [self.server.url]
                or self.headers.get("Sec-Fetch-Site") not in (None, "same-origin")):
            return self.respond({"error": "请求来源未授权"}, 403)
        if self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding"):
            return self.respond({"error": "只接受 JSON 请求"}, 415)
        session = self.session()
        hello = self.path == "/api/session"
        presented = self.headers.get("X-INF2-CSRF", "")
        if not hello and (not session or not presented.isascii() or not secrets.compare_digest(presented, session[1])):
            return self.respond({"error": "控制会话未授权"}, 403)
        try:
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isdigit() or not 2 <= int(lengths[0]) <= MAX_JSON:
                return self.respond({"error": "请求大小不合规"}, 400)
            data = json.loads(self.rfile.read(int(lengths[0])))
            if not isinstance(data, dict):
                raise ValueError("请求内容必须是对象")
            if hello:
                credentials = self.server.new_session(data.get("proof"))
                if not credentials:
                    return self.respond({"error": "启动凭据无效，请重新打开启动器"}, 403)
                token, csrf = credentials
                return self.respond({"csrf": csrf}, cookie=token)
            if self.path == "/api/action/close-panel":
                self.respond({"closed": True})
                Thread(target=self.server.shutdown, daemon=True).start()
                return
            if not self.path.startswith("/api/action/"):
                return self.respond({"error": "页面不存在"}, 404)
            manager = Manager(self.server.backend.home)
            with closing(manager.db):
                payload = self.server.backend.action(manager, self.path.removeprefix("/api/action/"), data, session[0])
            self.respond(payload)
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
            self.respond({"error": str(error)}, 409)


def fingerprint(home):
    return sha256(str(home).casefold().encode()).hexdigest()[:20]


def serve(home, port):
    home.mkdir(parents=True, exist_ok=True)
    with lease(home / "dashboard.lock") as acquired:
        if not acquired:
            raise ValueError("该队列已有面板服务")
        with Dashboard(home, port) as server:
            write(home / "dashboard-instance.json", {"port": server.server_port, "proof": server.bootstrap})
            print(f"INF2 已在 {server.url} 启动", flush=True)
            server.serve_forever()


def existing(home, port):
    record = read(home / "dashboard-instance.json")
    if not record or record["port"] != port:
        return None
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/health", timeout=.35) as response:
            health = json.load(response)
    except (OSError, URLError, ValueError):
        return None
    if isinstance(health, dict) and health.get("service") == "INF2" and health.get("instance") == fingerprint(home):
        return record | {"revision": health.get("revision")}
    return None


def close_old_service(home, port, record):
    url = f"http://127.0.0.1:{port}"
    opener = build_opener(ProxyHandler({}))
    headers = {"Origin": url, "Content-Type": "application/json"}
    try:
        with opener.open(Request(url + "/api/session", json.dumps({"proof": record["proof"]}).encode(),
                                 headers), timeout=4) as response:
            cookie = response.headers["Set-Cookie"].split(";", 1)[0]
            csrf = json.load(response)["csrf"]
        control = headers | {"Cookie":cookie, "X-INF2-CSRF":csrf}
        with opener.open(Request(url + "/api/action/close-panel", b"{}", control), timeout=4) as response:
            if json.load(response).get("closed") is not True:
                raise ValueError("旧服务未确认关闭")
    except (OSError, ValueError, KeyError, AttributeError) as error:
        raise ValueError("无法安全关闭旧版 Web 面板。请在旧面板的「资源与设置」关闭面板服务后再打开。") from error
    deadline = monotonic() + 8
    while existing(home, port):
        if monotonic() >= deadline:
            raise ValueError("旧版 Web 面板仍在退出。请等它关闭后再打开。")
        sleep(.12)


def ensure_service(home, port):
    revision = service_revision()
    record = existing(home, port)
    if record and record["revision"] != revision:
        close_old_service(home, port, record)
        record = None
    if not record:
        command = [sys.executable, "-X", "utf8", "-m", "tools.training_manager.dashboard", "--serve",
                   "--home", str(home.relative_to(HOME)), "--port", str(port)]
        with (home / "dashboard.log").open("ab") as log:
            process = detach(command, ROOT, log)
        deadline = monotonic() + 8
        while not record and monotonic() < deadline:
            sleep(.12)
            record = existing(home, port)
            if process.poll() is not None and not record:
                break
        if not record or record["revision"] != revision:
            raise ValueError(f"面板启动失败。请检查 {home/'dashboard.log'}")
    return record


def launch(home, port, browser=True):
    home.mkdir(parents=True, exist_ok=True)
    with lease(home / "dashboard-launch.lock") as acquired:
        if not acquired:
            raise ValueError("另一个启动器正在打开面板，请稍后重试。")
        record = ensure_service(home, port)
    url = f"http://127.0.0.1:{port}/"
    if browser and not webbrowser.open(url + "#" + record["proof"]):
        raise ValueError("面板已启动，但 Windows 未能打开默认浏览器")
    print(url)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=".")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        home = home_path(args.home)
        if not 1 <= args.port <= 65535:
            raise ValueError("无效的本地端口")
        if args.serve:
            serve(home, args.port)
        else:
            launch(home, args.port, not args.no_browser)
    except (OSError, ValueError) as error:
        print(f"INF2：{error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
