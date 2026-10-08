"""Where the backend listens, as a process the launcher started reaches it."""
import os


def backend_base_url():
    """``http://host:port`` for the backend, as reachable from this process.

    ``cli/environment.py::set_environment_variables`` exports FLASK_BACKEND_HOST/PORT and
    the launcher passes the environment to the processes it starts (the sandbox, the
    page server), so a process launched with the stack always has the true values -
    including on a custom-port stack, where the browser's own port would be wrong, and
    inside a container, where a host-published port is not the one to dial.

    The loopback host is normalised to 127.0.0.1: Node's fetch can stall when
    ``localhost`` resolves to IPv6 ::1 while Flask listens on IPv4 only.
    """
    host = os.environ.get('FLASK_BACKEND_HOST') or '127.0.0.1'
    port = os.environ.get('FLASK_BACKEND_PORT') or '5002'
    if host in ('localhost', '0.0.0.0', '::', '[::]'):
        host = '127.0.0.1'
    return f'http://{host}:{port}'
