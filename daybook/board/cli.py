# daybook board: serve the page, write today.md once, or print the state
import argparse
import json

from . import server


def main(argv=None):
    ap = argparse.ArgumentParser(prog="daybook board")
    ap.add_argument("cmd", choices=["serve", "digest", "state"])
    ap.add_argument("--host", default=None, help="default DAYBOOK_HOST (127.0.0.1)")
    ap.add_argument("--port", type=int, default=None, help="default DAYBOOK_BOARD_PORT (8740)")
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        server.serve(a.host, a.port)
        return 0
    app = server.App()
    app.refresh()
    if a.cmd == "digest":
        app.write_digest()
        print(app.data / "today.md")
        return 0
    print(json.dumps(app.state(), indent=1, default=str))
    return 0
