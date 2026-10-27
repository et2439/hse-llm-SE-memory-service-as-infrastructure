"""Loopback-only annotation UI. Sends no gold to independent raters."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import webbrowser

from eval.annotation_store import AnnotationStore, ConflictError
from eval.common import ROOT
from eval.review import ReviewStore


def make_handler(store, port, token):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, data, content_type="application/json; charset=utf-8", filename=None):
            raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'nonce-" + token +
                             "'; style-src 'self' 'nonce-" + token + "'; connect-src 'self'; frame-ancestors 'none'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(raw)

        def check(self, *, api=False, write=False):
            if self.headers.get("Host") not in hosts:
                self.send(403, {"error": "Недопустимый адрес."})
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{host}" for host in hosts}:
                self.send(403, {"error": "Запрос с другой страницы отклонён."})
                return False
            if api and self.headers.get("X-Local-Token") != token:
                self.send(403, {"error": "Обновите страницу локального приложения."})
                return False
            return True

        def do_GET(self):
            if not self.check(api=self.path.startswith("/api/")):
                return
            if self.path == "/":
                page = (ROOT / "eval/annotation_ui.html").read_text().replace("__LOCAL_TOKEN__", token)
                self.send(200, page.encode(), "text/html; charset=utf-8")
            elif self.path == "/api/state":
                try:
                    self.send(200, store.state())
                except ValueError as exc:
                    self.send(400, {"error": str(exc)})
            elif self.path == "/api/export":
                self.send(200, store.export(), "application/octet-stream",
                          "review.json" if isinstance(store, ReviewStore) else "annotations-" + store.reviewer + ".zip")
            else:
                self.send(404, {"error": "Страница не найдена."})

        def do_POST(self):
            if not self.check(api=True, write=True):
                return
            if self.path != "/api/action":
                self.send(404, {"error": "Неизвестное действие."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1_000_000 or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("Неверный формат запроса.")
                payload = json.loads(self.rfile.read(length))
                self.send(200, store.mutate(payload))
            except ConflictError as exc:
                self.send(409, {"error": str(exc)})
            except (ValueError, KeyError, TypeError) as exc:
                self.send(400, {"error": str(exc)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer", choices=("a", "b", "review"), default="a")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        store = ReviewStore() if args.reviewer == "review" else AnnotationStore(args.reviewer)
        token = secrets.token_urlsafe(32)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), BaseHTTPRequestHandler)
        server.RequestHandlerClass = make_handler(store, server.server_port, token)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Не удалось открыть разметку: {exc}\n")
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Локальная разметка: {url}", flush=True)
    print("Ответы сохраняются на этом компьютере. Для остановки нажмите Ctrl+C.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
