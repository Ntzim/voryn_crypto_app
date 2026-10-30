import socket

from app.serve import dual_stack_socket


def test_ipv6_host_also_accepts_ipv4() -> None:
    if not socket.has_ipv6:
        return
    sock = dual_stack_socket("::", 0)
    try:
        sock.listen()
        port = sock.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass
    finally:
        sock.close()
