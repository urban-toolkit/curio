import os
import time
import pytest
import subprocess
from signal import SIGINT

@pytest.fixture(scope="session")
def current_server():
    """Start the Sandbox server with environment variables"""
    env = os.environ.copy()
    env["FLASK_ENV"] = "testing"
    env["SECRET_KEY"] = "mysecretkey"

    process = subprocess.Popen(
        ["python", "server.py"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    time.sleep(2)  # Wait for the server to start
    yield "http://127.0.0.1:5002"
    process.terminate()


@pytest.fixture(scope="session")
def sandbox_server(request, app):
    """Start Backend live server for testing"""
    """Start Flask test server using virtual environment"""
    SANDBOX_PORT = app.config["SANDBOX_PORT"]
    VENV_PYTHON = os.path.join(
        os.getcwd(), app.config["SANDBOX_RELATIVE_PATH"], "sandenv", "bin", "python"
    )  # Linux/macOS
    env = os.environ.copy()
    env["FLASK_ENV"] = "testing"
    env["SECRET_KEY"] = "mysecretkey"
    env["FLASK_RUN_PORT"] = str(SANDBOX_PORT)
    process = subprocess.Popen(
        [VENV_PYTHON, "server.py"],
        cwd=os.path.join(os.getcwd(), app.config["SANDBOX_RELATIVE_PATH"]),
        env=env,
    )

    time.sleep(5)  # Wait for the server to start
    yield "http://127.0.0.1:2000"
    process.terminate()



def is_port_in_use(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0

@pytest.fixture(scope="session")
def frontend_server(app, request, current_server, sandbox_server):
    """Start the Frontend server with environment variables"""
    FRONTEND_PORT = app.config["FRONTEND_PORT"]
    if is_port_in_use(FRONTEND_PORT):
        completed = subprocess.run(["npx", "kill-port", str(FRONTEND_PORT)])
        assert completed.returncode == 0

    original_env = os.environ.copy()
    original_env["DONT_REWRITE_URLS"] = "false"
    original_env["PORT"] = str(FRONTEND_PORT)

    FRONTEND_CWD = os.path.join(os.getcwd(), app.config["FRONTEND_RELATIVE_PATH"])

    process = subprocess.Popen(
        ["npm", "run", "start:e2e"],
        cwd=FRONTEND_CWD,
        env=original_env,
        close_fds=True,
    )

    time.sleep(2)  # Wait for the server to start

    def kill_all():
        process.send_signal(SIGINT)
        process.terminate()
        process.wait()
        if is_port_in_use(FRONTEND_PORT):
            completed = subprocess.run(["npx", "kill-port", str(FRONTEND_PORT)])
            assert completed.returncode == 0

    request.addfinalizer(kill_all)

    yield f"http://127.0.0.1:{FRONTEND_PORT}"
    process.terminate()
