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
