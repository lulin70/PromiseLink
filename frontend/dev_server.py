#!/usr/bin/env python3
"""Dev static server with API proxy to backend."""
import os
import sys
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler

BACKEND = 'http://127.0.0.1:8000'

class DevHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        self.directory = directory or os.getcwd()
        super().__init__(*args, directory=self.directory, **kwargs)

    def _proxy(self):
        url = BACKEND + self.path
        try:
            req = urllib.request.Request(url, method=self.command,
                                         headers={k: v for k, v in self.headers.items() if k.lower() not in ('host',)},
                                         data=self.rfile.read(int(self.headers.get('Content-Length', 0))) if self.command in ('POST','PUT','PATCH') else None)
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in ('transfer-encoding', 'content-length'):
                        self.send_header(k, v)
                body = resp.read()
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in ('transfer-encoding', 'content-length'):
                    self.send_header(k, v)
            body = e.read()
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith('/api/'):
            return self._proxy()
        path = self.translate_path(self.path)
        if not os.path.exists(path) or os.path.isdir(path):
            self.path = '/index.html'
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith('/api/'):
            return self._proxy()
        self.send_error(405)

    def do_PATCH(self):
        if self.path.startswith('/api/'):
            return self._proxy()
        self.send_error(405)

    def do_DELETE(self):
        if self.path.startswith('/api/'):
            return self._proxy()
        self.send_error(405)

    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    directory = sys.argv[2] if len(sys.argv) > 2 else 'dist'
    os.chdir(os.path.join(os.path.dirname(__file__), directory))
    server = HTTPServer(('0.0.0.0', port), DevHandler)
    print(f'Dev server running at http://0.0.0.0:{port}')
    server.serve_forever()
