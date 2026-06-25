#!/usr/bin/env python3
"""Simple SPA static server with history fallback."""
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

class SPAHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        self.directory = directory or os.getcwd()
        super().__init__(*args, directory=self.directory, **kwargs)

    def do_GET(self):
        path = self.translate_path(self.path)
        if not os.path.exists(path) or os.path.isdir(path):
            self.path = '/index.html'
        return super().do_GET()

    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    directory = sys.argv[2] if len(sys.argv) > 2 else 'dist'
    os.chdir(os.path.join(os.path.dirname(__file__), directory))
    server = HTTPServer(('0.0.0.0', port), SPAHandler)
    print(f'SPA server running at http://0.0.0.0:{port}')
    server.serve_forever()
