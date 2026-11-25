import argparse
import os

import uvicorn


def main():
    parser = argparse.ArgumentParser(
        description="Run Nexus on loopback. See README for private HTTPS access."
    )
    parser.add_argument("--port", type=int, default=8765)
    options = parser.parse_args()
    if os.geteuid() == 0:
        parser.error("Run Nexus as an unprivileged account")
    os.umask(0o077)
    uvicorn.run(
        "nexus.app:make_app",
        factory=True,
        host="127.0.0.1",
        port=options.port,
        workers=1,
        access_log=False,
        proxy_headers=False,
        server_header=False,
        limit_concurrency=48,
        ws_max_size=4096,
        ws_max_queue=2,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=10,
    )


if __name__ == "__main__":
    main()
