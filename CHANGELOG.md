# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The engine contract: `Engine`, its values and events, and the `Store` and
  `Toolbox` ports, in `kataloop-core`. Specified in `docs/specs/engine.md`.
- `Kataloop`, the engine: one turn over uni-llm-client's `stream`, its tool
  calls run together through the `Toolbox`, failures as error results, paused
  turns sent back, rounds bounded by `RoundsExceededError`, the deadline, and
  cancellation that closes the model's stream. Specified in
  `docs/specs/turn.md`.
- `LocalToolbox`, the tools of the process's own, and `MemoryStore`, memory
  that lasts as long as the process.
- Unit tests of the core, run with `uv run pytest`.

[Unreleased]: https://github.com/the-guish/kataloop/commits/main
