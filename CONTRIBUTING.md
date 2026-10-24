# Contributing to kataloop

## Branching model

`main` is the only long-lived branch and must always be releasable. Direct
pushes to `main` are blocked.

1. Create a short-lived branch from `main` for each change, prefixed with
   `feature/` for new functionality or `fix/` for corrections:

       git switch main && git pull
       git switch -c feature/short-description

2. Open a pull request against `main`.
3. A maintainer merges it once checks pass and review is complete.

Maintainers cut releases by tagging a commit on `main` with a
[Semantic Versioning](https://semver.org/) tag such as `v0.2.0`. The Python
packages take their version from the tag and release together.

## Repository layout

Each port lives in `packages/<language>`. The Python port is a
[uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) of two
packages in `packages/python`: `kataloop-core`, which depends on uni-llm-client
and nothing else, and `kataloop`, which adds the extras that need a dependency.
The language-agnostic tests live in `tests`, and every port must pass them. A
port joins them through its test server, described in
[tests/README.md](tests/README.md). The test server is test code: it lives in
the port's `tests` directory and ships in no package.

## Coverage

Coverage comes from the HTTP tests in [`tests`](tests/README.md) alone. Each
port runs its test server under its coverage tool while the HTTP tests drive
it. Unit tests report no coverage, in every port.

## Development setup

The Python port uses [uv](https://docs.astral.sh/uv/). Run the same checks as
CI before opening a pull request. `kataloop` runs on both majors of the MCP
SDK, and an environment holds one, so the checks run once per major, each in
an environment of its own that `UV_PROJECT_ENVIRONMENT` names. In
`packages/python`, for mcp 1:

    export UV_PROJECT_ENVIRONMENT=.venv-mcp-1
    uv sync --locked --extra mcp-1
    uv run --locked ruff check
    uv run --locked ruff format --check
    uv run --locked mypy --always-false MCP_2 --exclude '_mcp2\.py$'
    uv run --locked pytest

and for mcp 2:

    export UV_PROJECT_ENVIRONMENT=.venv-mcp-2
    uv sync --locked --extra mcp-2
    uv run --locked mypy --always-true MCP_2 --exclude '_mcp1\.py$'
    uv run --locked pytest

Ruff reads the code alike in either, so once is enough; why mypy takes those
flags is in [packages/python/CONTRIBUTING.md](packages/python/CONTRIBUTING.md).
Then the HTTP tests, with the same checks of their own code, in `tests`, which
has an environment of its own:

    unset UV_PROJECT_ENVIRONMENT
    uv sync --locked
    uv run --locked ruff check
    uv run --locked ruff format --check
    uv run --locked mypy
    uv run --locked pytest

They start the Python test server once in each of the two environments, under
`coverage`; `uv run coverage combine` and `uv run coverage report` in
`packages/python` read what the two runs covered of both packages.

Until uni-llm-client is released, it is a git dependency pinned to a commit in
`packages/python/pyproject.toml`, which is why `uv sync` builds it rather than
running with `--no-build`.

The TypeScript port uses npm. Installs are `npm ci`, never `npm install`:

    cd packages/typescript
    npm ci
    npm run typecheck

New source files start with the license header:

    # Copyright 2026 The kataloop Authors
    # SPDX-License-Identifier: Apache-2.0

Each Python package ships copies of `LICENSE`, `NOTICE` and `AUTHORS`. Edit the
files at the root, then copy them to `packages/python/kataloop-core` and
`packages/python/kataloop`.

## Developer Certificate of Origin

All contributions must be signed off under the
[Developer Certificate of Origin 1.1](https://developercertificate.org/).
Add `-s` to your commit:

    git commit -s -m "component: short imperative summary"

which appends:

    Signed-off-by: Jane Doe <jane@example.com>

Use your real name and a reachable email address. Sign-off is a statement about
the provenance of your contribution, so pseudonymous sign-offs cannot be
accepted. If you are contributing on behalf of an employer, make sure you have
their authorization.
