# Contributing to jobsparser

This guide outlines the development and release process for `jobsparser`. We use `make` for common tasks and `uv` for environment management and publishing.

## Development Setup

To set up your development environment:

1.  Run the setup command:
    ```bash
    make setup_jobsparser_env
    ```

## Building the Package

To build the `jobsparser` package:

```bash
make build-jobsparser
```

## Publishing to PyPI

Publishing is handled by the `make publish-jobsparser` command, which uses `uv publish`.

### Authentication

`uv publish` requires an API token from PyPI.

1.  Create an API token on PyPI if you don't have one: [https://pypi.org/manage/account/token/](https://pypi.org/manage/account/token/)
2.  In the **root of the workspace** (where the `Makefile` is located), create a `.env` file. If an `.env.example` file exists, you can copy it:
    ```bash
    cp .env.example .env
    ```
    Otherwise, create a new `.env` file.
3.  Add your PyPI token to this `.env` file. `uv` typically uses the `UV_TOKEN` environment variable for PyPI authentication. The `publish-jobsparser` Make target is configured to load this `.env` file.
    Example content for your `.env` file:
    ```env
    # In your .env file (ensure this file is in .gitignore!)
    UV_TOKEN=pypi-your-api-token-here
    ```
    The `Makefile` loads variables from `.env`, making `UV_TOKEN` available to `uv publish`.

### Publishing Steps

1.  **Update Version**: Increment the version number in `jobsparser/pyproject.toml`.
2.  **Publish to PyPI**:
    ```bash
    make publish-jobsparser
    ```

## Testing Local Installation

After building the package, you can test if it installs and imports correctly using a dedicated make target:

```bash
make test-install-jobsparser
```
This command first ensures the package is built, then uses `uv run` to execute a simple import test (`import jobsparser`) within the context of the project's virtual environment.


## Running jobsparser locally

```bash
./run_local.sh <jobsparser_args>
```

E.g.
```bash
./run_local.sh --search-term "data engineer" --location "London" --site linkedin
```


