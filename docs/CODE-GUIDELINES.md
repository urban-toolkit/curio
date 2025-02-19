# Code Guidelines

This document outlines the coding conventions, best practices, and structural rules for contributing to this project. Read the whole document before contributing.

## Table of Contents

- [General principles](#general-principles)
- [Project structure](#project-structure)
- [Naming Conventions](#naming-conventions)
- [Contribution guidelines and standards](#contribution-guidelines-and-standards)
- [Documentation](#documentation)
- [Commit message guidelines](#commit-message-guidelines)
- [Automated tools](#automated-tools)

## Project structure

Keep files where they belong.

- **`backend/`**: Manages database access and user authentication.
- **`images/`**: Images for documentation.
- **`sandbox/`**: Sandbox for executing python code inside Curio.
- **`urban-workflows/`**: Manages database access and user authentication.
    - **`src/`**: Curio's source code.
        - **`components/`**: React components and respective CSS. Create a different file for each component. Keep similar components groupped inside folders.
- **`utk-workflow/`**: Stores a version of [UTK](https://github.com/urban-toolkit/utk) that can be embedded.

## Naming conventions

## Contribution guidelines and standards

Before sending your pull request for [review](https://github.com/urban-toolkit/curio/pulls), make sure your changes are consistent with the guidelines.

### General guidelines and philosophy for contribution

- Include unit tests when you contribute new features, as they help to a) prove that your code works correctly, and b) guard against future breaking changes to lower the maintenance cost.
- Bug fixes also generally require unit tests, because the presence of bugs usually indicates insufficient test coverage.
- Unit testing: Aim for >90% incremental test coverage for all your code (check [writing tests](#writing-tests)).
- Only add new dependencies if strictly necessary.

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

## Writing code

Contributions should be self-contained as to keep the code modularized. As a rule of thumb, Curio should be able to keep working if your code is removed.  

Every contribution implements **one** new feature or fixes **one** bug. Very similar features and bugs can be groupped into one contribution.  

One contribution = One pull request.  

### Considerations for new features

- Create new components for new features. 
- Modify a component if expanding a feature.
- Components must be as independent of each other as possible. If one component depends on another, create a reusable API or simple communication interface.
- New features should have a clear scope.
- Write unit tests for the new features aiming for >90% incremental test coverage for all your code (check [writing tests](#writing-tests)).

### Considerations for fixing bugs

- Careful to not introduce new bugs while fixing a bug.
- Bugs usually exist due to the lack of tests. Write unit tests after fixing a bug aiming for >90% incremental test coverage for all your code (check [writing tests](#writing-tests)).

### Issues management

If you open a GitHub Issue:

1. It must be a bug/performance issue or a feature request or a build issue or a documentation issue (for small doc fixes please send a PR instead).
2. Make sure the Issue Template is filled out.
3. The issue should be related to the repo it is created in.

Individual support should be sought on the Discord channel. It helps us to address bugs and feature requests in a timely manner.

## Writing tests

TODO

## Running unit tests

TODO

## Automated Tools

### Eslint and Prettier on `urban-workflows`

```console
npm run lint -- --fix
npm run format
```

### End-to-End tests on `backend/`

```shell
# after everything is setup, you can run the E2E tests
python -m pytest tests/test_frontend
```




