# 🚀 Installation Guide

This guide will help you get Curio up and running on your system. Curio includes a multi-server management tool that orchestrates three key components: the **Backend** for provenance tracking and user management, the **Sandbox** for executing code modules, and the **Frontend** for building visual workflows.

!!! info "System Requirements"
    - **Python >= 3.10 & < 3.12**
    - Tested on Windows 11, macOS Sonoma 14.5, and Ubuntu
    - [Docker](https://docs.docker.com/get-started/get-docker/) (for Docker installation method)

---

## 🎯 Installation Overview

The `curio` launcher is a unified command-line tool for starting, stopping, and rebuilding the various Curio servers. Depending on your installation method, you'll use either:

- `curio` command (if installed via pip)
- `python curio.py` command (if installed from Git repository)

You can inspect the help message by running:

=== "Via pip"
    ```bash
    curio --help
    ```

=== "From Git"
    ```bash
    python curio.py --help
    ```

**Sample output:**
```bash
Usage:
  curio start                       # Start all servers (Backend, Sandbox, Frontend)
  curio start backend               # Start only the backend (localhost:5002)
  curio start sandbox               # Start only the sandbox (localhost:2000)
  curio start --verbose VERBOSE     # Verbosity level (e.g., 0=silent, 1=normal, 2=debug)
  curio start --force-rebuild       # Re-build the frontend and start all servers
  curio start --force-db-init       # Re-initialize the backend database and start all servers
```

---

## ⚡ Quick Installation (Recommended)

The fastest way to get started with Curio:

```bash
# Install Curio
pip install utk-curio

# Start all components
curio start
```

!!! success "That's it!"
    This will start the backend, sandbox, and frontend servers. The first time Curio runs, it will automatically install UTK. Curio's frontend will be available at **http://localhost:8080**.

---

## 📦 Installation Methods

Choose the installation method that best fits your needs:

=== "Via pip (Quick Setup)"

    **Perfect for:** Quick setup and general usage

    ```bash
    pip install utk-curio
    ```

    **Starting Curio:**
    ```bash
    # Start all components
    curio start

    # Or start components individually
    curio start backend
    curio start sandbox
    curio start frontend
    ```

    !!! warning "Frontend Limitations"
        The pip installation includes a pre-built frontend and does not support rebuilding it. If you need to modify or rebuild the frontend, please use the manual installation method.

=== "Via Docker (Containerized)"

    **Perfect for:** Easy deployment and consistent environments

    **Prerequisites:** [Docker](https://docs.docker.com/get-started/get-docker/)

    ```bash
    # Clone the repository
    git clone git@github.com:urban-toolkit/curio.git
    cd curio

    # Start with Docker Compose
    docker compose up
    ```

    For older Docker versions:
    ```bash
    docker-compose up
    ```

    !!! info "Docker Notes"
        - Initial builds can take time
        - Use `--build` flag to rebuild if needed
        - Curio's frontend will be available at **http://localhost:8080**

=== "Manual Installation (Development)"

    **Perfect for:** Development, customization, and frontend modifications

    **Step 1: Clone and setup environment**
    ```bash
    # Clone the repository
    git clone git@github.com:urban-toolkit/curio.git
    cd curio

    # Create conda environment (recommended)
    conda create -n curio python=3.10
    conda activate curio
    ```

    **Step 2: Install dependencies**
    ```bash
    # Install Python requirements
    pip install -r requirements.txt

    # Install Node.js
    conda install -c conda-forge nodejs=22.13.0
    ```

    **Step 3: Start Curio**
    ```bash
    # Start all components
    python curio.py start

    # Or start individual servers
    python curio.py start backend
    python curio.py start sandbox
    python curio.py start frontend
    ```

    **Additional options:**
    ```bash
    # Force rebuild the frontend
    python curio.py start --force-rebuild

    # Force re-initialize the backend database
    python curio.py start --force-db-init
    ```

    !!! info "First Run"
        The first time Curio runs, it will automatically install UTK. The installation of all required packages might take a few minutes.

---

## 🖼️ Ray Tracing Support

To use Ray Tracing capabilities, please see UTK's [requirements](https://github.com/urban-toolkit/utk).

---

## ➡️ Next Steps

Congratulations! You've successfully installed Curio. Here's what to do next:

!!! tip "Get Started"
    Follow our [Quick Start Tutorial](quick_start.md) for a hands-on introduction to Curio's capabilities.

**Additional Resources:**  
- 🔧 [User Guide](../user-guide/overview.md) - Detailed documentation  
- 💬 [Discord Community](https://discord.gg/vjpSMSJR8r) - Get help and connect with users  
- 🐛 [Report Issues](https://github.com/urban-toolkit/curio/issues) - Found a bug?  

---

**Ready to build amazing urban analytics workflows?** Get started with a [Quick Start Tutorial](quick_start.md)! 🎉