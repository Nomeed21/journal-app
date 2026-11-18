"""Start the local server and open the browser once it is ready."""
import sys
from pathlib import Path
import socket
import threading
import time
import webbrowser

# Scripts launched by path otherwise search scripts/ before the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

HOST = "127.0.0.1"
PORT = 8000


def main():
    # Bind ourselves so another application cannot take the port between a
    # check and server startup. Never open an unrelated service in the browser.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((HOST, PORT))
        sock.listen(128)
    except OSError:
        sock.close()
        print(f"Port {PORT} is already in use. Close the other server and try again.")
        return 1

    server = uvicorn.Server(uvicorn.Config("main:app", host=HOST, port=PORT))

    def open_when_ready():
        while not server.started and not server.should_exit:
            time.sleep(0.1)
        if server.started:
            webbrowser.open(f"http://{HOST}:{PORT}/")

    threading.Thread(target=open_when_ready, daemon=True).start()
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()
    return 0 if server.started else 1


if __name__ == "__main__":
    raise SystemExit(main())
