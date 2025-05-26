#!/usr/bin/env python3

import subprocess
import os
import sys
import time
import threading
import queue
import argparse
import signal
import platform

output_queue = queue.Queue()
shell_required = platform.system() == "Windows"

# Ensure unbuffered output (immediate print)
os.environ["PYTHONUNBUFFERED"] = "1"
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# ANSI color codes for clear distinction
COLOR_RESET = "\033[0m"
COLOR_FRONTEND = "\033[96m"  # Cyan
COLOR_BACKEND = "\033[92m"   # Green
COLOR_SANDBOX = "\033[93m"   # Yellow

shutdown_flag = threading.Event()
processes = []

def stream_output(process, name, color):
    """Safely stream subprocess output."""
    try:
        while process.poll() is None and not shutdown_flag.is_set():
            # Read output line by line
            line = process.stdout.readline()
            if line:
                print(f"{color}[{name}] {line.strip()}{COLOR_RESET}")
        
        print(f"{color}[{name}] has stopped. No more output.{COLOR_RESET}")
    except ValueError:
        print(f"{color}[{name}] Error: Output stream closed unexpectedly.{COLOR_RESET}")
    finally:
        # Ensure the output streams are properly closed
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()

def set_environment_variables(backend_host, backend_port, sandbox_host, sandbox_port):
    """Sets the environment variables for Backend and Sandbox."""
    os.environ["FLASK_BACKEND_HOST"] = backend_host
    os.environ["FLASK_BACKEND_PORT"] = str(backend_port)
    os.environ["FLASK_SANDBOX_HOST"] = sandbox_host
    os.environ["FLASK_SANDBOX_PORT"] = str(sandbox_port)
    
    print(f"Environment Variables Set:")
    print(f"FLASK_BACKEND_HOST={os.environ['FLASK_BACKEND_HOST']}")
    print(f"FLASK_BACKEND_PORT={os.environ['FLASK_BACKEND_PORT']}")
    print(f"FLASK_SANDBOX_HOST={os.environ['FLASK_SANDBOX_HOST']}")
    print(f"FLASK_SANDBOX_PORT={os.environ['FLASK_SANDBOX_PORT']}")

def logger():
    """
    Continuously reads from the queue and prints to the terminal.
    """
    while True:
        line = output_queue.get()
        if line is None:
            break
        print(line)
        output_queue.task_done()

def check_install_build(dir, force_rebuild=False):
    # Determine the absolute path whether it is provided as relative or absolute
    script_dir = os.path.dirname(os.path.abspath(__file__))
    abs_dir = os.path.abspath(dir) if os.path.isabs(dir) else os.path.join(script_dir, dir)
    
    if not os.path.exists(abs_dir):
        raise FileNotFoundError(f"[Error] The directory '{abs_dir}' does not exist.")
    
    os.chdir(abs_dir)
    print(f"{COLOR_FRONTEND}[Frontend] Current working directory for npm commands: {os.getcwd()}{COLOR_RESET}")
    
    if force_rebuild:
        print(f"{COLOR_FRONTEND}[Frontend] Force rebuilding in {dir}...")
        if os.path.exists("node_modules"):
            subprocess.run(["rm", "-rf", "node_modules"], check=True)
        if os.path.exists("dist"):
            subprocess.run(["rm", "-rf", "dist"], check=True)
        if os.path.exists("build"):
            subprocess.run(["rm", "-rf", "build"], check=True)
    
    # Check if node_modules exist, if not, run npm install
    if not os.path.exists("node_modules"):
        print(f"{COLOR_FRONTEND}[Frontend] node_modules not found. Running npm install...{COLOR_RESET}")
        try:
            subprocess.run(["npm", "install"], check=True, shell=shell_required)
        except Exception as e:
            print(f"{COLOR_FRONTEND}[Frontend] Unexpected Error: {str(e)}{COLOR_RESET}")
            clean_shutdown()
    else:
        print(f"{COLOR_FRONTEND}[Frontend] node_modules directory already exists. Skipping npm install.{COLOR_RESET}")

    # Check if dist/build directory exists (depending on your setup)
    build_dir = "dist" if os.path.exists("dist") else "build"
    if not os.path.exists(build_dir):
        print(f"{COLOR_FRONTEND}[Frontend] {build_dir} directory not found. Running npm run build...{COLOR_RESET}")
        try:
            subprocess.run(["npm", "run", "build"], check=True, shell=shell_required)
        except Exception as e:
            print(f"{COLOR_FRONTEND}[Frontend] Unexpected Error: {str(e)}{COLOR_RESET}")
            clean_shutdown()
    else:
        print(f"{COLOR_FRONTEND}[Frontend] {build_dir} directory exists. Skipping npm run build.{COLOR_RESET}")

def force_rebuild_frontend():
    print(f"{COLOR_FRONTEND}[Frontend] Force rebuild requested.{COLOR_RESET}")
    check_install_build("frontend/urban-workflows/", force_rebuild=True)
    check_install_build("frontend/utk-workflow/src/utk-ts", force_rebuild=True)
    print(f"{COLOR_FRONTEND}[Frontend] Force rebuild complete.{COLOR_RESET}")

def start_frontend(force_rebuild=False):
    original_dir = os.getcwd()
    check_install_build("frontend/utk-workflow/src/utk-ts", force_rebuild=force_rebuild)
    os.chdir(original_dir)
    check_install_build("frontend/urban-workflows/", force_rebuild=force_rebuild)
    os.chdir(original_dir)
    os.chdir("frontend/urban-workflows/")
    print(f"{COLOR_FRONTEND}[Frontend] Current working directory for npm commands: {os.getcwd()}{COLOR_RESET}")
    
    try:
        # Start the Node.js server
        process = subprocess.Popen(
            ["npm", "run", "start"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=shell_required,
            env={**os.environ}
        )
        threading.Thread(target=stream_output, args=(process, "Frontend", COLOR_FRONTEND), daemon=True).start()

        # Check if process exited unexpectedly
        if process.poll() is not None:
            print(f"{COLOR_FRONTEND}[Frontend] Error: Server exited with code {process.returncode}{COLOR_RESET}")
            print(f"{COLOR_FRONTEND}[Frontend] Error Output:\n{process.stderr.read()}{COLOR_RESET}")
            clean_shutdown()
    except subprocess.CalledProcessError as e:
        print("{COLOR_FRONTEND}[Frontend] Error running npm install:{COLOR_RESET}")
        print(f"{COLOR_FRONTEND}[Frontend] Exit Code: {e.returncode}{COLOR_RESET}")
        print(f"{COLOR_FRONTEND}[Frontend] Output:\n{e.output}{COLOR_RESET}")
        print(f"{COLOR_FRONTEND}[Frontend] Error Output:\n{e.stderr}{COLOR_RESET}")
    except subprocess.TimeoutExpired:
        print(f"{COLOR_FRONTEND}[Frontend] Error: Server took too long to start.{COLOR_RESET}")
        clean_shutdown()
    except Exception as e:
        print(f"{COLOR_FRONTEND}[Frontend] Unexpected Error: {str(e)}{COLOR_RESET}")
        clean_shutdown()

    print(f"{COLOR_FRONTEND}[Frontend] Frontend server started successfully.{COLOR_RESET}")
    return process

def prepare_backend_database(force=False):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.join(script_dir, "backend")
    db_file = os.path.join(backend_dir, "provenance.db")

    if not os.path.exists(db_file) or force:
        print(f"{COLOR_BACKEND}[Backend] Preparing backend database...{COLOR_RESET}")
        try:
            os.chdir(backend_dir)
            subprocess.run(["python", "create_provenance_db.py"], check=True)

            env = {**os.environ, "FLASK_APP": "server.py"}
            subprocess.run(["flask", "db", "upgrade"], check=True, env=env)
            subprocess.run(["flask", "db", "migrate", "-m", "Migration"], check=True, env=env)
            os.chdir(script_dir)
            print(f"{COLOR_BACKEND}[Backend] Database initialized successfully.{COLOR_RESET}")
        except Exception as e:
            print(f"{COLOR_BACKEND}[Backend] Failed to initialize the database: {e}{COLOR_RESET}")
            clean_shutdown()
    else:
        print(f"{COLOR_BACKEND}[Backend] Database already exists. Skipping initialization.{COLOR_RESET}")


def start_backend(host, port, force_db_init=False):
    print(f"Starting backend on {host}:{port}...")

    prepare_backend_database(force=force_db_init)

    process = subprocess.Popen(
        ["python", "-u", "-m", "backend.server"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ}
    )
    threading.Thread(target=stream_output, args=(process, "Backend", COLOR_BACKEND), daemon=True).start()
    return process


def start_sandbox(host, port):
    print(f"Starting sandbox on {host}:{port}...")
    process = subprocess.Popen(
        ["python", "-u", "-m", "sandbox.server"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ}
    )
    threading.Thread(target=stream_output, args=(process, "Sandbox", COLOR_SANDBOX), daemon=True).start()
    return process

def signal_handler(sig, frame):
    """Handle SIGINT and SIGTERM for clean shutdown."""
    print("\nReceived shutdown signal (SIGINT or SIGTERM). Cleaning up...")
    clean_shutdown()

def clean_shutdown():
    print("\nShutting down all servers...")
    shutdown_flag.set()  # Signal threads to stop

    for process in processes:
        print(f"Terminating {process.args[0]}...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print(f"Force killing {process.args[0]}...")
            process.kill()

    print("All servers have been shut down.")
    # sys.stdout.flush()
    # sys.stderr.flush()
    sys.exit(0)  # Clean exit status (0)

def get_command_prefix():
    """Detects if the script is being run with 'python curio.py' or 'curio'."""
    if len(sys.argv) > 0:
        command = sys.argv[0]
        if command.endswith("curio.py"):
            return "python curio.py"
        elif command.endswith("curio"):
            return "curio"
    return "python curio.py"

def main():

    global processes

    # Capture Docker shutdown (SIGINT and SIGTERM)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    command_prefix = get_command_prefix()

    parser = argparse.ArgumentParser(
        description="Curio's multi-server management tool.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=f"""
    Examples:
        {command_prefix} start                       # Start all servers (Backend, Sandbox, Frontend)
        {command_prefix} start backend               # Start only the backend (localhost:5002)
        {command_prefix} start sandbox               # Start only the sandbox (localhost:2000)
        {command_prefix} start --force-rebuild       # Re-build the frontend and start all servers
        {command_prefix} start --force-db-init       # Re-initialize the backend database and start all servers
    """
    )
    
    parser.add_argument(
        "command", choices=["start"], help="Command to execute (start)"
    )
    parser.add_argument(
        "server", nargs="?", default="all", choices=["all", "frontend", "backend", "sandbox"],
        help="Script to manager Curio's servers (all, frontend, backend, sandbox)"
    )
    parser.add_argument(
        "--force-rebuild", action="store_true",
        help="Force rebuild of the frontend without starting"
    )
    parser.add_argument(
        "--force-db-init", action="store_true",
        help="Force re-initialization of the backend database"
    )
    parser.add_argument(
        "--backend-host", default="localhost", help="Host for the backend server (default: localhost)"
    )
    parser.add_argument(
        "--backend-port", default="5002", help="Port for the backend server (default: 5002)"
    )
    parser.add_argument(
        "--sandbox-host", default="localhost", help="Host for the sandbox server (default: localhost)"
    )
    parser.add_argument(
        "--sandbox-port", default="2000", help="Port for the sandbox server (default: 2000)"
    )

    # Display help if no arguments are given
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    set_environment_variables(
        backend_host=args.backend_host,
        backend_port=args.backend_port,
        sandbox_host=args.sandbox_host,
        sandbox_port=args.sandbox_port
    )

    if args.command == "start":

        if args.server == "all":
            print("Starting all servers (Backend, Sandbox, Frontend)...")
            processes = [
                start_backend(args.backend_host, args.backend_port, force_db_init=args.force_db_init),
                start_sandbox(args.sandbox_host, args.sandbox_port),
                start_frontend(force_rebuild=args.force_rebuild)
            ]
        else:
            if args.server == "backend":
                processes.append(start_backend(args.backend_host, args.backend_port))
            elif args.server == "sandbox":
                processes.append(start_sandbox(args.sandbox_host, args.sandbox_port))
            elif args.server == "frontend":
                processes.append(start_frontend(force_rebuild=args.force_rebuild))

        # Monitor the threads (logging simulation)
        logging_thread = threading.Thread(target=logger, daemon=True)
        logging_thread.start()

        try:
            while not shutdown_flag.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            clean_shutdown(processes)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()