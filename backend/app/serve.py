"""Production entry point: uvicorn on $HOST:$PORT.

With an IPv6 host (HOST=::, Railway's private network) the socket is bound dual-stack, so
IPv4 clients (health checks, older networks) still connect. Uvicorn alone would bind it
IPv6-only, because asyncio sets IPV6_V6ONLY on the sockets it creates.
"""

import os
import socket

import uvicorn


def dual_stack_socket(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.bind((host, port))
    sock.set_inheritable(True)
    return sock


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")  # noqa: S104 - a container must listen externally
    port = int(os.environ.get("PORT", "8000"))
    config = uvicorn.Config(
        "app.main:app",
        host=host,
        port=port,
        timeout_graceful_shutdown=20,
        # Client IPs come from the app's own rightmost-X-Forwarded-For logic.
        proxy_headers=False,
        server_header=False,
    )
    server = uvicorn.Server(config)
    if ":" in host:
        server.run(sockets=[dual_stack_socket(host, port)])
    else:
        server.run()


if __name__ == "__main__":
    main()
