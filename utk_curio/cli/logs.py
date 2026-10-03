"""Launcher output: the log file, terminal colors, verbosity and the line queue.

Importing this module also makes the launcher's stdout and stderr unbuffered.
"""

import logging
import os
import queue
import sys

from pathlib import Path


output_queue = queue.Queue()


# Ensure unbuffered output (immediate print)
os.environ["PYTHONUNBUFFERED"] = "1"
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# ANSI color codes for clear distinction
COLOR_RESET = "\033[0m"
COLOR_FRONTEND = "\033[96m"  # Cyan
COLOR_BACKEND = "\033[92m"   # Green
COLOR_SANDBOX = "\033[93m"   # Yellow


file_logger = None
verbosity = 1
logger = logging.getLogger(__name__)


def setup_logging(server: str = "all"):
    # CURIO_STATE_DIR relocates every per-stack file (backend/app/common/
    # user_storage.py); the log follows so two stacks in one checkout do not
    # truncate each other's -- ``filemode="w"`` below wipes the first
    # launcher's log the moment a second one starts. A single-server start
    # gets its own file for the same reason: an e2e shard is two launchers.
    log_dir = Path(os.environ.get("CURIO_STATE_DIR") or ".curio")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / ("messages.log" if server == "all" else f"messages-{server}.log")

    logging.basicConfig(
        filename=log_file,
        filemode="w",
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.DEBUG  # Capture all log levels in file
    )

    # Create helper log function for non-terminal info
    file_logger = logging.getLogger("file_only")
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_logger.addHandler(file_handler)
    file_logger.propagate = False

def log_always(message, verbose_level = 1):
    logging.info(message)
    if verbosity >= verbose_level or verbose_level == 0:
        print(f"{message}")

def log_info(message, color, verbose_level = 1):
    logging.info(message)
    if verbosity >= verbose_level or verbose_level == 0:
        print(f"{color}{message}{COLOR_RESET}")
            
def log_warning(message):
    """Logs a warning message to both the log file and terminal."""
    logging.warning(message)
    print(f"\033[93m[WARNING]\033[0m {message}", file=sys.stderr)

def log_error(message):
    """Logs an error message to both the log file and terminal."""
    logging.error(message)
    print(f"\033[91m[ERROR]\033[0m {message}", file=sys.stderr)


def logger():
    """
    Continuously reads from the queue and prints to the terminal.
    """
    while True:
        line = output_queue.get()
        if line is None:
            break
        log_always(line, 2)
        output_queue.task_done()
