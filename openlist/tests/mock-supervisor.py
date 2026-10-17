"""CI fixture, not a Home Assistant authorization implementation."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path != "/info" or self.headers.get("Authorization") != "Bearer ci-fixture":
            self.send_error(403)
            return
        payload = json.dumps({"result": "ok", "data": {"supervisor": Path("/fixtures/version").read_text().strip()}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


HTTPServer(("0.0.0.0", 80), Handler).serve_forever()
