# kataloop

A small agent loop: it asks a model, runs the tools the model asks for over
MCP, gives the results back, and goes on until the model answers, streaming
what happens and remembering the conversation. It reaches the vendors through
[uni-llm-client](https://github.com/the-guish/uni-llm-client). It is one of the
agent engines of [robinauts](https://github.com/the-guish/robinauts), and it
stands alone: a script, a job or any other caller can run it.

## Packages

| Package | Directory | Status |
|---|---|---|
| Python `kataloop-core` | [`packages/python/kataloop-core`](packages/python/kataloop-core) | Not started |
| Python `kataloop` | [`packages/python/kataloop`](packages/python/kataloop) | Not started |
| TypeScript | [`packages/typescript`](packages/typescript) | Not started |

`kataloop-core` depends on uni-llm-client and nothing else, and keeps its
memory in the process. `kataloop` adds what needs a dependency: MCP tool
servers, and PostgreSQL memory as `kataloop[postgres]`.

Every port follows the specs in [`docs/specs`](docs/specs), and the plan to a
first engine is in [`docs/plan.md`](docs/plan.md). Every port passes the
language-agnostic tests in [`tests`](tests/README.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
