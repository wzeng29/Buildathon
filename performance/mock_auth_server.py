from __future__ import annotations

import base64
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HOST = os.getenv("AUTH_HOST", "127.0.0.1")
PORT = int(os.getenv("AUTH_PORT", "3001"))
USERS_PATH = os.path.join(os.path.dirname(__file__), "data", "users.json")


def _load_users() -> dict[str, str]:
    with open(USERS_PATH, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    users: dict[str, str] = {}
    for item in payload:
        email = str(item.get("email", "")).strip()
        password = str(item.get("password", "")).strip()
        if email and password:
            users[email] = password
    return users


USERS = _load_users()


def _encode_jwt(payload: dict[str, object]) -> str:
    header = {"alg": "none", "typ": "JWT"}

    def encode_part(value: dict[str, object]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return f"{encode_part(header)}.{encode_part(payload)}."


class AuthHandler(BaseHTTPRequestHandler):
    server_version = "MockAuth/1.0"

    def _write_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._write_json(200, {"status": "ok"})
            return
        self._write_json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/auth/login":
            self._write_json(404, {"error": "Not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._write_json(400, {"error": "Invalid JSON"})
            return

        email = str(payload.get("email", "")).strip()
        password = str(payload.get("password", "")).strip()
        expected = USERS.get(email)
        if not expected or expected != password:
            self._write_json(401, {"error": "Invalid credentials"})
            return

        issued_at = int(time.time())
        expires_at = issued_at + 24 * 60 * 60
        token = _encode_jwt(
            {
                "sub": email,
                "email": email,
                "iat": issued_at,
                "exp": expires_at,
            }
        )
        self._write_json(
            200,
            {
                "data": {
                    "token": token,
                }
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), AuthHandler)
    print(f"Mock auth server listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()
