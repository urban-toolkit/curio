"""The launcher's child processes: streaming their output, watching them and
shutting them down."""

import platform
import subprocess
import sys
import threading
import time

from utk_curio.cli.logs import log_always, log_error, log_info


shell_required = platform.system() == "Windows"


shutdown_flag = threading.Event()
processes = []
#: What the launcher exits with once every server stopped: 0, or the status
#: of the stop a server's exit asked for (:func:`clean_shutdown`).
exit_status = 0
#: Once a server exited, how long :func:`watch` waits for
#: :func:`stream_output` to have logged what it wrote before it exited.
OUTPUT_WAIT_S = 5.0


def stream_output(process, name, color):
    """Safely stream subprocess output."""
    try:
        while process.poll() is None and not shutdown_flag.is_set():
            # Read output line by line
            line = process.stdout.readline()
            if line:
                log_info(f"[{name}] {line.strip()}", color, 2)
        if process.poll() is not None:
            # It exited: the lines it wrote last, often why it exited, are
            # still in the pipe.
            for line in process.stdout:
                log_info(f"[{name}] {line.strip()}", color, 2)
        log_info(f"[{name}] has stopped. No more output.", color, 1)
    except ValueError:
        log_error(f"[{name}] Error: Output stream closed unexpectedly.")
    finally:
        # Ensure the output streams are properly closed
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()


def watch(started, stop=None) -> None:
    """Until the launcher stops, look at each of *started*,
    ``[(name, process)]``, every second. As soon as one has exited while the
    launcher is not stopping, stop every server with an error through *stop*,
    told which and with which code, once the lines it wrote last are in the
    log (:data:`OUTPUT_WAIT_S`); by default :func:`_stop`.

    ``main()`` watches the servers a start runs itself, the backend group
    its backend processes and nginx (``backend_group.watch``)."""
    stop = stop or _stop
    while not shutdown_flag.is_set():
        for name, process in started:
            code = process.poll()
            if code is not None:
                _wait_for_its_output(process)
                if not shutdown_flag.is_set():
                    stop(f"{name} exited with code {code}")
                return
        time.sleep(1)


def _wait_for_its_output(process) -> None:
    """Wait, for at most :data:`OUTPUT_WAIT_S`, until :func:`stream_output`
    has read *process*, which exited, to its end: it closes its stdout then."""
    output = getattr(process, "stdout", None)
    if output is None:
        return
    deadline = time.monotonic() + OUTPUT_WAIT_S
    while not getattr(output, "closed", True) and time.monotonic() < deadline:
        time.sleep(0.05)


def _stop(why: str) -> None:
    log_error(f"[launcher] {why}: stopping every server")
    clean_shutdown(1)


def signal_handler(sig, frame):
    """Handle SIGINT and SIGTERM for clean shutdown."""
    log_always("\nReceived shutdown signal (SIGINT or SIGTERM). Cleaning up...")
    clean_shutdown()

def clean_shutdown(status=0):
    """Stop every server and exit with *status*: 0 when asked to stop, an
    error when a server stopped by itself or a start failed, so that a script
    never reads a failed start as one that came up. Called on another thread
    than the main one, it ends that thread, and the main one exits with
    *status* once it sees the servers stopped (``main.py``)."""
    global exit_status
    if status:
        exit_status = status
    log_always("\nShutting down all servers...")
    shutdown_flag.set()  # Signal threads to stop

    for process in processes:
        log_always(f"Terminating {process.args[0]}...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log_always(f"Force killing {process.args[0]}...")
            process.kill()

    log_always("All servers have been shut down.")
    sys.exit(exit_status)
