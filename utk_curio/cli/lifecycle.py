"""The launcher's child processes: streaming their output and shutting them down."""

import platform
import subprocess
import sys
import threading

from utk_curio.cli.logs import log_always, log_error, log_info


shell_required = platform.system() == "Windows"


shutdown_flag = threading.Event()
processes = []
#: What the launcher exits with once every server stopped: 0, or the status
#: of the stop a server's exit asked for (:func:`clean_shutdown`).
exit_status = 0


def stream_output(process, name, color):
    """Safely stream subprocess output."""
    try:
        while process.poll() is None and not shutdown_flag.is_set():
            # Read output line by line
            line = process.stdout.readline()
            if line:
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


def signal_handler(sig, frame):
    """Handle SIGINT and SIGTERM for clean shutdown."""
    log_always("\nReceived shutdown signal (SIGINT or SIGTERM). Cleaning up...")
    clean_shutdown()

def clean_shutdown(status=0):
    """Stop every server and exit with *status*: 0 when asked to stop, an
    error when a server stopped by itself. Called on another thread than the
    main one, it ends that thread, and the main one exits with *status* once
    it sees the servers stopped (``main.py``)."""
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
