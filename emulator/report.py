"""Serve the results page (evaluation/results/index.html).

The page reads the result records itself, so it shows whatever is in the
directory when it is loaded. It reads the verification reports
(evaluation/verification) the same way, for its support matrix. A browser cannot list a directory, and a web
server that finds an index.html does not list one either; this server answers
the page's request for the list.
"""
import functools
import http.server
import json
import webbrowser

from .errors import EmuError
from . import results
from .paths import RESULTS_DIR, VERIFICATION_DIR

LIST_PATH = "/records.list"
# The verification reports are beside the results, not among them; the page
# builds its support matrix from them.
VERIFICATION_PATH = "/verification/"


class _Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == VERIFICATION_PATH + "list":
            body = json.dumps(sorted(found.name for found in VERIFICATION_DIR.glob("*.json"))).encode()
        elif path.startswith(VERIFICATION_PATH):
            # One report, by its file name alone.
            found = VERIFICATION_DIR / path[len(VERIFICATION_PATH):]
            if found.parent != VERIFICATION_DIR or found.suffix != ".json" or not found.is_file():
                return self.send_error(404)
            body = found.read_bytes()
        elif path == LIST_PATH:
            body = json.dumps([path.name for path in results.record_paths()]).encode()
        else:
            return super().do_GET()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")       # records change between loads
        super().end_headers()

    def log_message(self, *args):
        pass


def serve(port, open_browser=True):
    handler = functools.partial(_Handler, directory=str(RESULTS_DIR))
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError as error:
        raise EmuError("cannot serve the results on port %d: %s" % (port, error), hint="choose another with --port")
    address = "http://127.0.0.1:%d/" % server.server_address[1]
    print("emu: the results are at %s (Ctrl-C to stop)" % address, flush=True)
    if open_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
