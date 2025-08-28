# 🎓 Onboarding Guide for UTK, Curio, and Urbanite

This guide is designed for **undergraduate students** to help you get started quickly and independently with UTK, Curio, and Urbanite projects.



<!-- ---

## 📋 Table of Contents

1. [🏗️ Project Overview](#-project-overview)
2. [⚙️ Core Technologies](#%EF%B8%8F-core-technologies)
3. [💾 Essential Installations](#-essential-installations)
4. [📁 Repository Organization](#-repository-organization)
5. [🤝 Making Contributions](#-making-contributions)
6. [🚀 Usage and Quick Start](#-usage-and-quick-start)
7. [💡 Getting Help](#-getting-help)
8. [✅ Onboarding Checklist](#-onboarding-checklist)
9. [❓ Frequently Asked Questions](#-frequently-asked-questions) -->

---

## 🏗️ Project Overview

The Urban Toolkit ecosystem consists of three interconnected frameworks:

=== "UTK (Urban Toolkit)"

    **A flexible and extensible visualization framework that enables the easy authoring of web-based visualizations through a new high-level grammar specifically built with common urban use cases in mind.**

    - 🎯 **Purpose:** High-level grammar for web-based urban visualizations
    - 🔗 **Repository:** [GitHub](https://github.com/urban-toolkit/utk)
    - 📊 **Focus:** Data visualization and interactive urban analytics

=== "Curio"

    **Built on top of UTK, Curio is a framework for collaborative urban visual analytics that uses a dataflow model with multiple abstraction levels (code, grammar, GUI elements) to facilitate collaboration across the design and implementation of visual analytics components. The framework allows experts to intertwine preprocessing, managing, and visualization stages while tracking provenance of code and visualizations.**

    - 🎯 **Purpose:** Dataflow-based collaborative urban visual analytics
    - 🔗 **Repository:** [GitHub](https://github.com/urban-toolkit/curio)
    - 🔧 **Features:** Multi-abstraction levels, provenance tracking, GUI workflow builder

=== "Urbanite"

    **Urbanite extends the dataflow-based approach by incorporating large language models (LLMs) to enable human-AI collaboration in urban visual analytics. It allows users to specify intent at multiple scopes, enabling interactive alignment across specification, process, and evaluation stages, with features for explainability, multi-resolution task definition, and interaction provenance.**

    - 🎯 **Purpose:** Human-AI collaboration in urban visual analytics
    - 🔗 **Repository:** [GitHub](https://github.com/urban-toolkit/urbanite)
    - 🤖 **Features:** LLM integration, interactive alignment, explainability

!!! info "Framework Relationship"
    **UTK** → **Curio** → **Urbanite**  
    Curio uses UTK while Urbanite builds on Curio with LLM-powered capabilities. If you would like to learn more about the design and research behind these tools, please see the research papers linked in each repository.

---

## 🎨 Learning Philosophy
!!! success "Programming is Art" 
    "We have seen that computer programming is an art, because it applies accumulated knowledge to 
    the world, because it requires skill and ingenuity, and especially because it produces objects of 
    beauty. A programmer who subconsciously views himself as an artist will enjoy what he does and 
    will do it better."  
    — Donald Knuth


As you code for Curio, remember that things not working is a normal, expected part of programming. Debugging is not just about fixing mistakes; it is how programmers learn, understand, and improve their work. Each error you encounter is an opportunity to clarify your thinking, discover how the systems and frameworks truly work, and refine your design. **This is the craft you are developing.** Treat debugging and refinement as part of your learning, not interruptions to it.

As you learn, consider reading [Peter Norvig's "Teach Yourself Programming in Ten Years"](https://norvig.com/21-days.html). Norvig emphasizes that programming is not about shortcuts or overnight mastery but about learning deeply, practicing consistently, and staying curious while building meaningful systems. Likewise, Donald Knuth, one of the most respected computer scientists, describes programming as an art that requires creativity, skill, and the pursuit of clarity and beauty in your work. You can read his classic perspective in ["Computer Programming as an Art"](https://dl.acm.org/doi/pdf/10.1145/1283920.1283929).

When your code breaks or your pipeline fails, take a breath: this is not a reason for frustration, but an invitation to engage with programming and strengthen your ability to think, debug, and build effectively.

---


## ⚙️ Core Technologies

Curio is built using **React** and **TypeScript**. For an overview of React, see [this tutorial](https://react.dev/learn) and [this tutorial](https://beta.reactjs.org/learn).

### 🚀 How a React Program is Built and Deployed

A typical React application development and deployment pipeline follows these stages:

=== "1. Development"

    - Code is written in **TypeScript** using React components, typically with state management via hooks (e.g., `useState`, `useEffect`)
    - Development happens locally using **Webpack Dev Server**, which provides hot module reloading for a fast feedback loop
    - Styling is handled using CSS Modules

=== "2. Building"

    - The app is bundled and transpiled using **Webpack**, converting TypeScript and JSX into browser-compatible JavaScript
    - This process:
        - Minifies assets
        - Tree-shakes unused code  
        - Optimizes images and static assets for performance
    - The output is a `dist/` or `build/` folder containing:
        - `index.html`
        - Minified JS bundles (e.g., `main.[hash].js`)
        - CSS files
        - Other static assets

=== "3. Deployment"

    - The `dist/` or `build/` folder can be deployed to any web server
    - Environment variables (API keys, feature flags) are injected during build time or runtime using environment files (`.env`)

### 🏗️ How This is Handled in Curio

!!! info "Automated Management"
    In Curio, these stages are automated using `curio.py`, which manages building, serving, and orchestrating the **frontend, backend, and sandbox environments** during local development and testing.

However, you can also **build and serve each component manually** if needed:

=== "🎨 Frontend"

    **Build manually:**
    ```bash title="Manual Frontend Build"
    cd utk_curio/frontend/urban-workflows
    npm run build
    ```
    
    **Serve using:**
    ```bash title="Development Server"
    npm run start  # Webpack Dev Server with hot reload
    ```
    
    ```bash title="Production Server"
    python -m http.server 8080 --directory dist  # Serve built files
    ```

=== "🔧 Backend"

    **Run backend server:**
    ```bash title="Backend Server"
    cd utk_curio/backend
    python -m backend.server
    ```
    
    - Initializes the database if necessary before serving requests
    - Handles provenance tracking and user management

=== "⚙️ Sandbox"

    **Run sandbox server:**
    ```bash title="Sandbox Server"
    cd utk_curio/sandbox  
    python -m sandbox.server
    ```
    
    - Useful for isolated environment testing
    - Handles code execution in secure environment

!!! tip "Key Architecture Components"
    **Curio manages three key components automatically:**
    
    - **🔧 Backend:** Provenance tracking, user management
    - **⚙️ Sandbox:** Code execution environment  
    - **🎨 Frontend:** Visual workflow builder
    
!!! warning "Important Setup Notes"
    - **Start servers in appropriate folders:** Check `utk_curio/frontend/urban-workflows`, `utk_curio/backend`, `utk_curio/sandbox` folders to ensure relative imports and environment paths work correctly
    - **Multiple installation methods:** There are several ways to install and use Curio (pip, Docker, manual installation). Check the [Installation Guide](installation.md) for more details

### 🎨 Frontend Codebase Overview

The frontend architecture is built around modular React components:



#### 📁 Component Structure

The `MainCanvas` component is the heart of the editor:

**Location:** `utk_curio/frontend/urban-workflows/src/components/MainCanvas.tsx`

Inside the `components` folder, you'll find modular subcomponents:

- **`TableBox`** → renders and manages table nodes
- **`ImageBox`** → handles image nodes  
- **`UserMenu`, `ToolsMenu`, `TopMenu`** → UI layers

#### 🔧 Component Implementation

If you check the `MainCanvas.tsx` file, at around line 97, you'll see something similar to:

```tsx title="MainCanvas.tsx - Component Structure"
return (
    <div>
        <ReactFlow />
        <UserMenu />
        <ToolsMenu />
        {/* other components */}
    </div>
);
```

This JSX structure defines the editor layout with React components, not raw HTML. Components are implemented in separate files:

```tsx title="Component References"
<TopMenu />  // References: components/menu/top/TopMenu.tsx
```

Style classes (e.g., `className="rightSide"`) are defined in CSS module files (e.g., `UpMenu.module.css`).

---

## 💾 Essential Installations

Before starting, install these essential tools:

=== "Git"

    **Version Control System**
    
    - 📥 **Download:** [Git for Windows](https://git-scm.com/download/win)
    - 🖥️ **Includes:** Git Bash for command-line operations
    - 📚 **Tutorial:** [Git Quick Guide](https://rogerdudler.github.io/git-guide/)

=== "Python Environment"

    **Python Package Management**
    
    - 📥 **Download:** [Anaconda Distribution](https://www.anaconda.com/products/distribution)
    - 📚 **Tutorial:** [Getting Started with Conda](https://docs.conda.io/projects/conda/en/latest/user-guide/getting-started.html)
    - ✅ **Recommended:** Includes package management and environment isolation

!!! tip "Platform Support"
    All tools work on **Windows** (with Git Bash/WSL), **macOS**, and **Linux**. Choose the platform you're most comfortable with.

---

## 📁 Repository Organization

All Urban Toolkit repositories follow a consistent structure:

```
project-root/
├── docs/              # Documentation and guides
├── tests/             # Unit and integration tests  
├── utk_curio/         # Source code
│   ├── frontend/      # React/TypeScript UI
│   ├── backend/       # Python backend services
│   └── sandbox/       # Code execution environment
├── requirements.txt   # Python dependencies
└── README.md          # Project overview
```

!!! info "Consistency Across Projects"
    This structure is maintained across **UTK**, **Curio**, and **Urbanite** repositories with minor variations.

---

## 🤝 Making Contributions

We welcome and encourage contributions! Here's how to get involved:

### 📝 Contribution Types

=== "🐛 Bug Fixes"

    - Report issues with detailed reproduction steps
    - Include error messages and system information
    - Test fixes thoroughly before submitting

=== "📚 Documentation"

    - Improve clarity and completeness
    - Add examples and tutorials
    - Fix typos and formatting issues

=== "🎨 New Features"

    - Build new visualizations and components
    - Extend framework capabilities
    - Add new urban analytics workflows

### 🔄 Contribution Workflow

!!! tip "Before Contributing"
    1. Read the [Contribution Guidelines](https://github.com/urban-toolkit/curio/blob/main/docs/CONTRIBUTIONS.md)
    2. Check existing issues and pull requests
    3. Fork the repository and create a feature branch

**Remember:** *What you get is what you give.* The more you invest in exploring, building, and contributing, the more you'll learn and gain from these projects.

---

## 🚀 Usage and Quick Start

Ready to start building? Follow these resources:

!!! success "Quick Start Resources"
    
    - 🚀 **[Quick Start Guide](quick_start.md):** Get up and running immediately
    - 📖 **[Installation Guide](installation.md):** Detailed setup instructions

These guides will help you learn to run, modify, and contribute to the projects independently.

---

## 💡 Getting Help

When you need assistance, follow these best practices:

### 🎯 Help Channels

=== "💬 Discord (Preferred)"

    - Use [Discord channels](https://discord.gg/vjpSMSJR8r) for questions and discussions
    - Share code snippets and screenshots
    - Engage with the community

=== "📧 Email"

    - Use only when specifically requested or truly necessary
    - For urgent or sensitive issues

!!! tip "Be Proactive"
    Take initiative to search documentation, check previous issues, and try debugging independently. Help may be delayed, so self-reliance is valuable.

### 📋 When Asking for Help

Include this information to get faster, better assistance:

!!! example "Help Request Template"
    
    **1. Error Message:** Full error text  
    **2. Steps to Reproduce:** What you did before the error  
    **3. What You've Tried:** Your debugging attempts  
    **4. Screenshots:** Visual context if relevant  
    **5. Environment:** OS, Python version, installation method


---

## ✅ Onboarding Checklist

Use this checklist to guide your first week and ensure proper setup:

### 🛠️ Environment Setup

- [ ] **Install Git** and confirm `git` command works
- [ ] **Install Anaconda/Miniconda** and confirm `conda` is available
- [ ] **Fork and clone** your target repository (UTK/Curio/Urbanite)
- [ ] **Create Conda environment** for the project
- [ ] **Follow installation steps** from the repository documentation

### 🚀 First Run

- [ ] **Run the tool** to confirm everything works
- [ ] **Explore folder structure** and understand organization
- [ ] **Locate examples** and documentation
- [ ] **Identify contribution areas** of interest

### 🤝 Community Integration

- [ ] **Join Discord channel** for community support
- [ ] **Read contribution guidelines** thoroughly
- [ ] **Complete a small task** (documentation fix, example run)

!!! success "You're Ready!"
    Once you've completed this checklist, you're ready to start contributing meaningfully to the Urban Toolkit ecosystem!

---

## ❓ Frequently Asked Questions

### 🖥️ Platform and Tools

??? question "Should I use Windows?"
    
    **Yes!** Windows is fully supported with several options:
    
    - **Git Bash** (easiest to start)
    - **WSL (Windows Subsystem for Linux)**
    - **Windows Terminal**
    
    macOS and Linux are also fully supported.

??? question "What is Bash?"
    
    **Bash** is a command-line shell for running commands and scripts. Essential for development work.
    
    **Windows options:**
    - Git Bash (recommended for beginners)
    - Hyper terminal
    - Windows Terminal with WSL

??? question "What is Git?"
    
    **Git** is a version control system that lets you:
    - Track changes in your code
    - Collaborate with others
    - Manage your codebase systematically

### 🐍 Python Environment Management

??? question "Conda vs. Miniconda vs. Mamba?"
    
    === "Conda (Anaconda)"
        - **Full package:** Includes many pre-installed data science packages
        - **Best for:** Beginners who want everything included
        - **Size:** Larger installation
    
    === "Miniconda"  
        - **Minimal:** Install only what you need
        - **Best for:** Users who prefer lightweight setups
        - **Size:** Smaller installation
    
    === "Mamba"
        - **Fast alternative:** Drop-in replacement for Conda
        - **Best for:** Speed optimization
        - **Commands:** Same as Conda but faster

### 🔧 Troubleshooting

??? question "How do I fix errors or debug issues?"
    
    **Step-by-step debugging approach:**
    
    1. **Read documentation** in the repository first
    2. **Check setup instructions** carefully
    3. **Create a fork** if you need to make code changes
    4. **Test locally** before submitting issues or PRs
    5. **Ask for help** with detailed information

??? question "Why do I get 'no such file' when running `python curio.py start`?"
    
    **This means Python can't find `curio.py` in your current directory.**
    
    === "Solution 1: Navigate to Repository"
        ```bash
        cd path/to/your/cloned/repo
        python curio.py start
        ```
    
    === "Solution 2: Use pip Installation"
        ```bash
        pip install curio
        curio start  # Available from any folder
        ```

??? question "Why are there two different instances of `curio`?"
    
    **Different installation methods create different access patterns:**
    
    === "Via pip"
        - **Global access:** `curio` command available everywhere
        - **Location:** Python environment's  Scripts (Windows) or bin (macOS/Linux) folder, making it accessible system-wide from any folder.
    
    === "Via Git clone"
        - **Local access:** Must run from cloned folder unless you set up a manual path or install it using pip.
        - **Command:** `python curio.py start`

??? question "Why do I get `bash: conda: command not found`?"

    This error means Git Bash cannot find your `conda` installation because:
    - Git Bash does not automatically inherit the PATH used by Anaconda/Miniconda installed on Windows.
    - By default, `conda` is added to the Windows environment PATH, but Git Bash may need manual configuration to access it.

    To fix it, verify where Anaconda/Miniconda is installed. Typical installation paths include `C:\Users\<YourUsername>\Anaconda3` or `C:\Users\<YourUsername>\Miniconda3`. Then, add `conda` to your Git Bash path, replacing the appropriate paths:

    ```bash
    echo 'export PATH="/c/Users/<YourUsername>/Anaconda3:/c/Users/<YourUsername>/Anaconda3/Scripts:/c/Users/<YourUsername>/Anaconda3/Library/bin:$PATH"' >> ~/.bashrc
    ```

    (replace <YourUsername> with your Windows username and make sure the path is correct)

    Then, apply the changes:
    ```bash
    source ~/.bashrc
    ```

    Test if it works:
    ```bash
    conda --version
    ```

    If it returns a version, `conda` is now accessible in Git Bash.

    Also, if you want `conda activate` to work fully in Git Bash, initialize Conda for bash:
    ```bash
    conda init bash
    ```
    And then restart Git Bash. Check [this](https://discuss.codecademy.com/t/setting-up-conda-in-git-bash/534473) for even more information.

??? question "How do I know if my issue is with Curio, Conda, or Pip?"

    When troubleshooting, it helps to identify **where the problem actually is**:

    === "🔍 Curio Issues"
        - `curio start` (or `python curio.py start`) fails with app-specific errors
        - Curio-specific stack traces in error messages
        - Issues with workflows, visualization, or GUI components
        
        If the error mentions Curio-specific stack traces, it's a **Curio project issue** (wrong folder, misconfiguration, or a Curio bug).

    === "🐍 Conda Issues"  
        - `conda` gives `command not found`
        - Environment activation fails `conda activate` errors
        - Package installation problems in Conda
        
        If `conda` commands give `command not found` or environment activation fails (`conda activate` errors), it's a **Conda installation or PATH issue**. If packages are missing despite installation attempts inside Conda, verify you are in the correct environment:
        ```bash
        conda info --envs
        ```

    === "📦 Pip Issues"
        - `pip install` failures
        - Missing packages after pip installation
        - Wrong environment being used
        
        If `pip install` fails, or packages are missing after installation, it's typically a **pip issue** (wrong environment, missing dependencies, or permissions). Check which environment `pip` is using:
        ```bash
        which pip
        pip --version
        ```
        Ensure it matches your active environment (`conda info`).

    If you are still unsure, please gather the following so we can pinpoint whether it's **Curio, Conda, or Pip** and resolve it:
    
    !!! example "Diagnostic Information to Collect"
        **1. The exact command you ran**
        
        **2. The full error message**
        
        **3. Current working directory:**
        ```bash
        pwd
        ```
        
        **4. Environment information:**
        ```bash
        which python
        which pip
        conda info --envs
        ```

??? question "Why does `curio start` take so long the first time?"
    
    !!! info "This is normal behavior!"
    
    **First run processing:**
    - Node.js frontend compilation
    - Asset bundling and optimization
    - Dependency installation
    - Cache building
    
    **Expected time:** 30 seconds to a few minutes
    **Subsequent runs:** Much faster due to caching

??? question "I get 'No such file or directory' when loading a file"
    
    **File paths are relative to your current working directory.**
    
    **Check your location:**
    ```bash
    pwd  # See current directory
    ls   # List files in current directory
    ```
    
    **Ensure you're running Curio from the correct folder.**

---

!!! tip "Ready to Start?"
    Congratulations on completing the onboarding guide! You now have everything you need to contribute meaningfully to the Urban Toolkit ecosystem. 
    
    **Next step:** Try the [Quick Start Tutorial](quick_start.md) to build your first visualization! 🎉 