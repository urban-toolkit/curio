# Code Guidelines

This document outlines the coding conventions, best practices, and structural rules for contributing to this project. Adhering to these guidelines ensures consistency, readability, and maintainability.

## Table of Contents

- [General Principles](#general-principles)
- [Project Structure](#project-structure)
- [Naming Conventions](#naming-conventions)
- [Contribution guidelines and standards](#contribution-guidelines-and-standards)
- [Documentation](#documentation)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Automated Tools](#automated-tools)

## General Principles

- Write clean, readable, and maintainable code.
- Follow the "Principle of Least Surprise" — your code should do what other developers expect it to do.
- Use comments sparingly but effectively; avoid redundant comments.

## Project Structure

- **`backend/`**: Manages databases access and user authentication.
  - **`requirements.txt`**: All Python dependencies for PyPi should be listed here (avoid adding new dependecies).
  - **`services/`**: Application logic, API calls, and data handling.
  - **`utils/`**: Reusable utility functions and helpers.

- **`tests/`**: Contains all test files, typically following the same structure as `src/`.

- **`docs/`**: Documentation files, such as guides, architecture explanations, or additional Markdown files.

- **`public/`**: Static assets accessible in the application, such as images, favicon, or index.html for web apps.

- **`.eslintrc`**: ESLint configuration file to enforce code standards.

- **`.prettierrc`**: Prettier configuration for consistent code formatting.

- **`package.json`**: Lists dependencies, scripts, and project metadata.

- **`README.md`**: Main entry point for understanding the project, including setup instructions, usage, and contribution guidelines.

## Naming Conventions

## Contribution guidelines and standards

Before sending your pull request for [review](https://github.com/urban-toolkit/curio/pulls), make sure your changes are consistent with the guidelines.

### General guidelines and philosophy for contribution

- Include unit tests when you contribute new features, as they help to a) prove that your code works correctly, and b) guard against future breaking changes to lower the maintenance cost.
- Bug fixes also generally require unit tests, because the presence of bugs usually indicates insufficient test coverage.
- Unit testing: Aim for >90% incremental test coverage for all your code (check [writing tests](#writing-tests)).

### React and JSX coding style

Changes to Curio React and JSX code should conform to [Airbnb React/JSX Style Guide](https://airbnb.io/javascript/react/). 

The [Javascript coding style](#javascript-coding-style) takes precedence in case of conflicts.

### Javascript coding style

Changes to Curio Javascript code should conform to [Google JavaScript Style Guide](https://google.github.io/styleguide/jsguide.html).

### Python coding style

Changes to Curio Python code should conform to [Google Python Style Guide](https://github.com/google/styleguide/blob/gh-pages/pyguide.md).

Use pylint to check your Python changes. To install pylint and check a file with pylint:

```bash
pip install pylint
pylint myfile.py
```

### Writing tests


### Running unit tests

## Commit Message Guidelines

## Automated Tools






