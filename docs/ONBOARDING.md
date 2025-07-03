# Onboarding Document for UTK, Curio, and Urbanite

This document is meant for **undergraduate students** involved in UTK, Curio, and Urbanite projects to get you started quickly and independently.

## 1. Overview: UTK, Curio, and Urbanite

- **UTK (Urban Toolkit):** A flexible and extensible visualization framework that enables the easy authoring of web-based visualizations through a new high-level grammar specifically built with common urban use cases in mind. [GitHub](https://github.com/urban-toolkit/utk)

- **Curio:** Built on top of UTK, Curio is a framework for collaborative urban visual analytics that uses a dataflow model with multiple abstraction levels (code, grammar, GUI elements) to facilitate collaboration across the design and implementation of visual analytics components. The framework allows experts to intertwine preprocessing, managing, and visualization stages while tracking provenance of code and visualizations. [GitHub](https://github.com/urban-toolkit/curio)

- **Urbanite:** Building on Curio, Urbanite extends the dataflow-based approach by incorporating large language models (LLMs) to enable human-AI collaboration in urban visual analytics. It allows users to specify intent at multiple scopes, enabling interactive alignment across specification, process, and evaluation stages, with features for explainability, multi-resolution task definition, and interaction provenance. [GitHub](https://github.com/urban-toolkit/urbanite)

Curio uses UTK while Urbanite builds on Curio with LLM-powered capabilities. If you would like to learn more about the design and research behind these tools, please see the research papers linked in each repository.

## 2. Essential Installations

Install these tools before you start:

- **Git for Windows:** Download and install [Git for Windows](https://git-scm.com/download/win). It comes with Git Bash, which you will use for command-line operations. See [here](https://rogerdudler.github.io/git-guide/) for a quick Git tutorial.
  
- **Python and Pip:** Download and install [Anaconda](https://www.anaconda.com/products/distribution) for Python environment management. For understanding how to manage Python with Conda, see [Getting Started with Conda](https://docs.conda.io/projects/conda/en/latest/user-guide/getting-started.html).

## 3. General Organization of Documents

This folder structure represents the **overall structure followed in each of the UTK, Curio, and Urbanite repositories**:

- `docs/` – Usage guides, examples, contribution guidelines, developer references
- `tests/` – Unit tests and integration tests
- `utk_curio/` – Source code for the UTK and Curio frameworks

This **structure is followed across each repository (UTK, Curio, Urbanite) with minor variations**.

## 4. Making Contributions

You are encouraged to contribute! Please read our [Contribution Guidelines](https://github.com/urban-toolkit/curio/blob/main/docs/CONTRIBUTIONS.md) before submitting pull requests.

Contributions can include:
- Fixing bugs
- Adding examples
- Improving documentation
- Building new visualizations with Curio or Urbanite

Remember: **what you get is what you give**. The more you invest in exploring, building, and contributing, the more you will learn and gain from these projects. It is up to you how much you get out of this experience.

## 5. Usage and Quick Start

To learn how to use Curio:

 - Quick Start: Follow the Quick Start Guide for immediate steps to run your first visualization.
 - Usage Guide: Review the Usage Guide to understand the workflows, architecture, and examples in Curio.

These guides will help you learn how to run, modify, and contribute to the projects independently.

## 5. Tips for Seeking Help

- Use **Discord channels** to ask questions and share issues.
- Use email for help requests only if it is specifically requested or truly necessary.
- Being proactive is important; there may be days when help is delayed, so take initiative to search the documentation, check previous issues, and try debugging on your own.
- When asking for help, provide as much information as possible:
  - The error message.
  - Steps to reproduce the error.
  - What you have tried already.
  - Screenshots if relevant.

## 6. Task List

Use this list to guide your first week of onboarding and to ensure your environment is correctly set up:

- [ ] **Install Git for Windows** and confirm `git` is available in your terminal.
- [ ] **Install Anaconda** (or Miniconda + Mamba) and confirm `conda` is available.
- [ ] **Fork and clone the repository** you will work on (UTK, Curio, or Urbanite).
- [ ] **Create and activate your Conda environment.**
- [ ] **Refer to the repository for installation steps.**
- [ ] **Run the tool** to confirm everything is working.
- [ ] **Explore the folder structure** and identify:
    - Where examples live
    - Where to add new scripts or visualization specs
    - How documentation is organized
- [ ] **Join the Discord channel**.
- [ ] **Read the CONTRIBUTIONS.md** to understand how to submit contributions.
- [ ] **Complete a first small task** (e.g., fixing a typo in documentation or running an existing example).

## 7. FAQ

### Should I use Windows?

Yes, you can use Windows with Git Bash or WSL for bash support. Alternatively, MacOS and Linux are also fully supported.

### What is Bash?

Bash is a command-line shell used to run commands and scripts. It is essential for running many scripts used in these projects. There are several options for Bash on Windows (e.g., Git Bash, Hyper, Windows Terminal with WSL). It’s up to you which one you prefer, but Git Bash is the easiest to get started.

### What is Git?

Git is a version control system that allows you to track changes in your code, collaborate with others, and manage your codebase systematically.

### What is the difference between Conda, Miniconda, and Mamba?

- **Conda** is a package and environment manager bundled with Anaconda, which includes many pre-installed packages useful for data science and visualization.
- **Miniconda** is a minimal installer for Conda, letting you install only what you need, saving disk space.
- **Mamba** is a fast, drop-in replacement for Conda with the same commands, speeding up environment creation and package installation.

You can use any of these for managing your Python environments. If you want simplicity, use Anaconda; for lightweight flexibility, use Miniconda or Mamba.

### How do I fix errors or debug issues?

First, read the documentation in the repository. Check the documentation for setup. If you need to make code changes to debug, create a fork of the repository, make your changes there, and test locally before submitting any issues or pull requests for help.

### What if I encounter issues during installation?

Check the Discord channels for pinned troubleshooting steps or ask a clear question with error details.

### Why do I get “no such file” when running python curio.py start?

If you are getting an error like:
```bash
python: can't open file 'curio.py': [Errno 2] No such file or directory
```
it means Python cannot find `curio.py` in your current working directory. To solve it, you must run the command inside the folder where you cloned the repository, where curio.py is located:

```bash
cd path/to/your/cloned/repo
python curio.py start
```

If you installed the project using pip (e.g., pip install curio), it will install the entry point automatically, allowing you to run the following from any folder without needing to be in the project directory:

```bash
curio start
```
