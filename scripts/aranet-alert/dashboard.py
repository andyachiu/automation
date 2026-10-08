"""Read-only dashboard; bind to a private Tailscale address for deployment."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from history import snapshot

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url=urlparse(self.path)
        if url.path == '/':
            body=Path(__file__).with_name('dashboard.html').read_bytes()
            kind='text/html; charset=utf-8'
        elif url.path == '/api/readings':
            try:
                hours=int(parse_qs(url.query).get('hours',['24'])[0])
                if hours not in (2,6,24,168): raise ValueError()
            except ValueError:
                self.send_error(400,'Choose 2, 6, 24 or 168 hours'); return
            try:
                payload=snapshot(hours)
                payload['threshold']=int(os.environ.get('CO2_HIGH','1000'))
                payload['stale_seconds']=int(os.environ.get('STALE_MINUTES','15'))*60
                body=json.dumps(payload,allow_nan=False).encode()
            except Exception:
                self.send_error(503,'History unavailable'); raise
            kind='application/json'
        else:
            self.send_error(404); return
        self.send_response(200)
        self.send_header('Content-Type',kind)
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'")
        self.send_header('Content-Length',str(len(body)))
        self.end_headers(); self.wfile.write(body)

if __name__=='__main__':
    ThreadingHTTPServer((os.environ.get('DASHBOARD_BIND','127.0.0.1'),int(os.environ.get('DASHBOARD_PORT','8080'))),Handler).serve_forever()
