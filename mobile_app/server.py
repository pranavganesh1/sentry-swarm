import http.server
import socketserver
import json
import os
import time
import sys
from pathlib import Path

PORT = 8000
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
MOBILE_DIR = WORKSPACE_DIR / "mobile_app"
ACTIVE_SNAPSHOT = WORKSPACE_DIR / "logs" / "active_incidents.json"
METRICS_FILE = WORKSPACE_DIR / "logs" / "mttd_metrics.json"

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Multi-threaded HTTP server to handle concurrent SSE subscriptions."""
    daemon_threads = True

class MobileResponderHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence standard request logging to avoid log pollution, but allow printing startup info
        pass

    def do_GET(self):
        """Route GET requests to the SSE stream or static file handler."""
        if self.path == '/events':
            self.handle_sse()
        else:
            self.handle_static()

    def handle_sse(self):
        """Stream server-sent events with active and resolved incident data.

        Keeps the connection open, polling the snapshot files every second
        and pushing a JSON payload only when the data has changed.
        """
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        last_payload = None

        print(f"[{time.strftime('%H:%M:%S')}] Client subscribed to mobile SSE stream.")

        while True:
            try:
                # 1. Read Active Incidents
                active = []
                if ACTIVE_SNAPSHOT.exists():
                    try:
                        with open(ACTIVE_SNAPSHOT, encoding='utf-8') as f:
                            active = json.load(f)
                    except Exception:
                        pass

                # 2. Read Resolved Incidents
                resolved = []
                if METRICS_FILE.exists():
                    try:
                        with open(METRICS_FILE, encoding='utf-8') as f:
                            resolved = json.load(f)
                    except Exception:
                        pass

                payload = {
                    "active": active,
                    "resolved": resolved
                }

                # Only send if data changed
                payload_str = json.dumps(payload)
                if payload_str != last_payload:
                    self.wfile.write(f"data: {payload_str}\n\n".encode('utf-8'))
                    self.wfile.flush()
                    last_payload = payload_str

                # Sleep to check again
                time.sleep(1.0)
            except (ConnectionResetError, BrokenPipeError):
                print(f"[{time.strftime('%H:%M:%S')}] Client disconnected from SSE stream.")
                break
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] Error in SSE loop: {e}", file=sys.stderr)
                break

    def handle_static(self):
        """Serve static files from the mobile_app directory with path sanitisation."""
        # Normalize and sanitize path
        cleaned_path = self.path.split('?')[0].strip('/')
        if not cleaned_path or cleaned_path == '':
            cleaned_path = 'index.html'

        file_path = (MOBILE_DIR / cleaned_path).resolve()

        # Security check: ensure path is inside the mobile_app directory
        if not str(file_path).startswith(str(MOBILE_DIR.resolve())):
            self.send_error(403, "Access Denied")
            return

        if not file_path.is_file():
            self.send_error(404, "File Not Found")
            return

        # Determine Mime Type
        mime_type = 'application/octet-stream'
        if file_path.suffix == '.html':
            mime_type = 'text/html; charset=utf-8'
        elif file_path.suffix == '.js':
            mime_type = 'application/javascript; charset=utf-8'
        elif file_path.suffix == '.css':
            mime_type = 'text/css; charset=utf-8'
        elif file_path.suffix == '.json':
            mime_type = 'application/json; charset=utf-8'
        elif file_path.suffix == '.png':
            mime_type = 'image/png'
        elif file_path.suffix == '.svg':
            mime_type = 'image/svg+xml'
        elif file_path.suffix == '.ico':
            mime_type = 'image/x-icon'
        elif file_path.suffix == '.webp':
            mime_type = 'image/webp'
        elif file_path.suffix == '.woff2':
            mime_type = 'font/woff2'

        try:
            with open(file_path, 'rb') as f:
                content = f.read()

            self.send_response(200)
            self.send_header('Content-Type', mime_type)
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Internal Server Error: {e}")

def main():
    """Start the threaded HTTP server for the mobile responder UI."""
    server_address = ('', PORT)
    try:
        httpd = ThreadingHTTPServer(server_address, MobileResponderHandler)
        print(f"==================================================")
        print(f"Sentry-Swarm Mobile Responder Server Active")
        print(f"Serving UI at: http://localhost:{PORT}")
        print(f"SSE Endpoint:  http://localhost:{PORT}/events")
        print(f"Press Ctrl+C to terminate.")
        print(f"==================================================")
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down mobile responder server.")
    except Exception as e:
        print(f"Failed to start server: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
