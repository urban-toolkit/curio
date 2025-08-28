# 🤝 Contributing to Curio

Welcome to the **Curio** contributing guide! We're excited to collaborate on developing a framework for collaborative urban visual analytics that is both accessible and powerful. This guide is designed for students interested in contributing to open-source software, as well as developers looking to participate in the Curio ecosystem.

!!! tip "New Contributors Welcome!"
    Whether you're building your first pull request or integrating advanced features, this document is designed to support your contribution journey. Check out our [GitHub Issues](https://github.com/urban-toolkit/curio/issues) for good first tasks!

!!! note "About Curio"
    Curio is actively evolving. Expect changes, and if you hit a snag, open a GitHub Issue—we’re here to help!

---

## 🌟 Why Contribute

Contributing to Curio offers the opportunity to:

- 🚀 **Gain experience** with a modern tech stack used in both research and industry
- 🔬 **Understand** how visual analytics systems are built from the ground up  
- 👥 **Collaborate** with a team of researchers and urban analytics experts
- 📁 **Build** a public portfolio of meaningful contributions (code, documentation, testing)
- 🌍 **Engage** with real-world urban data: mobility, accessibility, environmental datasets

---

## 🛠️ Technology Overview

Curio's architecture consists of multiple integrated components:

| Component | Technology | Function |
|-----------|------------|----------|
| **Backend** | Python, Flask | REST API for managing users, workflows, and provenance |
| **Frontend** | JavaScript, UTK, Vega-Lite | Browser-based interface for authoring and interacting with dataflows |
| **Execution** | Python sandbox (multiprocess) | Secure module for executing user code |
| **DevOps** | Docker, Docker Compose, GitHub Actions | Containerization, deployment, and CI/CD |
| **Packaging** | PyPI (`utk-curio`) | Distributes the CLI and backend/frontend bundle |

---

## 📁 Repository Structure

The codebase follows a modular structure under the `utk_curio/` directory:

```
curio/
├── utk_curio/
│   ├── backend/                     # Manages database access and user authentication
│   │   └── tests/                   # pytest files for backend
│   ├── sandbox/                     # Executes user Python code in a secure environment
│   │   └── tests/                   # pytest files for sandbox
│   └── frontend/                    # All frontend logic
│       ├── urban-workflows/         # Main Curio interface for dataflow editing
│       │   └── src/
│       │       └── components/      # React components and CSS
│       └── utk-workflow/            # Embedded version of UTK
│
├── curio.py                         # CLI entry point for running and managing all services
├── tests/                           # Dataflow examples for testing
├── docs/                            # Documentation, usage guides, and examples
└── requirements.txt                 # Backend and sandbox dependencies
```

---

## 🚀 Installation Options

Choose the installation method that fits your contribution goals:

=== "Via pip (Quick Setup)"

    **Perfect for:** Testing and basic usage

    ```bash
    pip install utk-curio
    curio start
    ```

    !!! warning "Frontend Limitations"
        This installs the CLI and a pre-built version of the frontend. You won't be able to modify or rebuild the UI from this setup.

=== "From GitHub (Development)"

    **Perfect for:** Contributing code, developing features, and frontend modifications

    ```bash
    git clone https://github.com/urban-toolkit/curio.git
    cd curio
    python curio.py start
    ```

    !!! tip "Full Development Setup"
        Refer to our [Installation Guide](getting-started/installation.md) for complete Docker instructions and frontend build steps.

---

## 🎯 Suggested Contribution Paths

| Contribution Area | Specific Tasks |
|-------------------|----------------|
| **🧪 Testing and Debugging**<br>Improve test coverage and reliability | • Write or improve `pytest` tests in `backend/tests` and `sandbox/tests`<br>• Reproduce and resolve issues from GitHub<br>• Extend test coverage for edge cases<br>• Test Curio across platforms (Windows, macOS, Linux) |
| **🔧 Developing Dataflow Nodes**<br>Extend Curio's analytical capabilities | • Add new analytic operations as reusable nodes<br>• Improve UI and metadata descriptions |
| **📊 Example Workflows**<br>Create learning resources for users | • Create dataflow examples using public datasets<br>• Annotate dataflows to serve as tutorials<br>• Contribute to the `examples/` directory |
| **📚 Documentation**<br>Make Curio more accessible | • Write developer setup instructions or onboarding checklists<br>• Add usage diagrams, screenshots, or schema explanations<br>• Contribute inline documentation and docstrings<br>• Improve API documentation |
| **🌐 Community and Support**<br>Help grow the Curio community | • Suggest improvements to onboarding and usability<br>• Help with community support on Discord<br>• Create tutorials and learning resources |

---

## 🏁 Getting Started (Step-by-Step)

### 1. Fork and Clone the Repository

!!! info "Forking the Repository"
    Visit the [Curio GitHub page](https://github.com/urban-toolkit/curio) and click the "Fork" button in the upper-right corner. For more details, see GitHub's [Forking a repo](https://docs.github.com/en/get-started/quickstart/fork-a-repo) guide.

After forking:

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/curio.git
cd curio

# Set the original repository as upstream
git remote add upstream https://github.com/urban-toolkit/curio.git
```

### 2. Set Up Development Environment

```bash
# Create conda environment (recommended)
conda create -n curio python=3.10
conda activate curio

# Install dependencies
pip install -r requirements.txt
```

### 3. Run the System

```bash
python curio.py start
```

!!! success "Development Server Running"
    Open your browser and navigate to **http://localhost:8080** to access the Curio interface.

### 4. Create a Feature Branch

```bash
git checkout -b my-feature
```

### 5. Make Changes and Commit

```bash
git add .
git commit -m "Add: feature description"
git push origin my-feature
```

### 6. Submit a Pull Request


Open a PR on GitHub with a detailed description and link to relevant issues. **When you create a PR, make sure you create a PR selecting the branch of the upstream repository you'd like to merge changes into (usually urban-toolkit/curio main).**

---

## 📋 Organizing Contributions

### Defining the Scope of a Pull Request

!!! important "Focus Your PRs"
    Each PR should ideally address a single feature or issue. Avoid mixing unrelated changes as it makes the review process harder and less transparent.

**Focus on:**  
- ✅ One feature addition  
- ✅ One bug fix    
- ✅ One set of related documentation updates  

If your PR grows beyond a single scope, consider splitting it into multiple PRs.

### Pull Request Template

Use this template when creating a Pull Request:

```markdown
# Describe your changes


# Issue resolved by this PR (if any)
 - Issue Number:
 - Link:

# Type of change (Check all that apply)
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation Update
- [ ] Other: 

# Parts of Curio impacted by this PR:
- [ ] Frontend
- [ ] Backend
- [ ] Sandbox

# Testing
 - [ ] Unit Tests
 - [ ] Manual Testing (please provide details below)

# Screenshots (if relevant)


# Checklist (Check all that apply)
- [ ] I have manually loaded each .json test from the `tests/` folder into Curio, ran all the nodes one by one, and checked that they run without errors and give the expected results
- [ ] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation
- [ ] My changes generate no new warnings
- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] New and existing unit tests pass locally with my changes
- [ ] Any dependent changes have been merged and published in downstream modules
```

### Issue Template

!!! tip "Before Creating Issues"
    - Check if the issue already exists
    - Provide as much relevant detail as possible

```markdown
### Summary
<!-- Provide a concise description of the issue. -->

### Steps to Reproduce
<!-- List the steps to replicate the problem -->

### Expected Result
<!-- What did you expect to happen? -->

### Actual Result
<!-- What actually happened? -->

### Environment
<!-- OS, Browser, Node version, Branch, etc. -->

### Additional Information
<!-- Screenshots, logs, temporary workarounds, etc. -->
```

---

## 🎓 Advice for Students

!!! tip "Getting Started Tips"
    - **Start small** - improving documentation or examples is a valuable first step
    - **Ask questions early**, especially if you're unfamiliar with the stack
    - **Use GitHub Issues** to propose ideas and get feedback
    - **Consider pairing** contributions with coursework or independent study
    - **Reach out for mentorship** if you're committing to a larger contribution


---

### Development Resources

- 📖 [Installation Guide](getting-started/installation.md) - Complete setup instructions
- 🚀 [Quick Start Tutorial](getting-started/quick_start.md) - Learn the basics
- 📚 [User Guide](user-guide/overview.md) - Detailed documentation
- 🎯 [Examples](examples/examples.md) - Real-world use cases

---

## 🎉 Final Notes

Every contribution helps! You don't need deep expertise—just curiosity, commitment, and a willingness to learn. Whether you're fixing a typo in documentation or implementing a new dataflow node, your work makes Curio better for the entire urban analytics community.

**Ready to contribute?** Start by exploring our [GitHub Issues](https://github.com/urban-toolkit/curio/issues) and join our [Discord community](https://discord.gg/vjpSMSJR8r)!

Happy contributing! 🌍✨
