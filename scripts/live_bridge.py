"""LIVE end-to-end: real camera + synthetic engine -> SSE -> bridge ->
mock Event service. Not part of the test suite (needs the LAN camera)."""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import uvicorn

from opal_look.app import create_app
from opal_look.event_bridge import BridgeConfig, EventBridge

LOOK_PORT = 18096
EVENT_PORT = 18097
published = []


class EventHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        published.append(body)
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(
            {"id": "evt-live-1", "status": "accepted",
             "published_at": "2026-01-01T00:00:00Z"}).encode())

    def log_message(self, *a):
        pass


def free(p):
    s = socket.socket(); s.bind(("127.0.0.1", p)); s.close()


def main():
    from opal_look.dotenv import prepare
    prepare()                                # load repo-root .env
    event_srv = HTTPServer(("127.0.0.1", EVENT_PORT), EventHandler)
    threading.Thread(target=event_srv.serve_forever, daemon=True).start()

    app = create_app()
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=LOOK_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()

    look = httpx.Client(base_url=f"http://127.0.0.1:{LOOK_PORT}",
                        timeout=30.0)
    for _ in range(50):
        try:
            look.get("/health"); break
        except httpx.HTTPError:
            time.sleep(0.2)

    look.post("/api/v1/model/synthetic-det/load")
    r = look.post("/api/v1/stream/", json={
        "source": "rtsp://192.168.1.220:554/stream1",
        "credential_ref": "FRONT", "name": "front",
        "engine_id": "synthetic", "model_id": "synthetic-det"})
    print("admission:", r.status_code)
    sid = r.json()["stream_id"]

    for _ in range(60):
        if look.get(f"/api/v1/stream/{sid}").json()["status"] == "running":
            break
        time.sleep(0.5)

    cfg = BridgeConfig(look_url=f"http://127.0.0.1:{LOOK_PORT}",
                       event_url=f"http://127.0.0.1:{EVENT_PORT}",
                       stream_id="front", reconnect_backoff=0.5)
    bridge = EventBridge(cfg)
    t = threading.Thread(target=bridge.run, daemon=True)
    t.start()

    deadline = time.time() + 30
    while not published and time.time() < deadline:
        time.sleep(0.5)
    print("published:", json.dumps(published[:1], indent=1)[:800])

    look.post(f"/api/v1/stream/{sid}/stop")
    t.join(timeout=15)
    print("bridge done: published=%d suppressed=%d dropped=%d" %
          (bridge.published, bridge.suppressed, bridge.dropped))
    server.should_exit = True
    event_srv.shutdown()


if __name__ == "__main__":
    main()
