# kataloop

A small agent loop: it asks a model, runs the tools the model asks for over
MCP, gives the results back, and goes on until the model answers, streaming
what happens and remembering the conversation. It reaches the vendors through
uni-llm-client.

This package re-exports [`kataloop-core`](https://pypi.org/project/kataloop-core/)
and adds what needs a dependency: MCP tool servers, and PostgreSQL memory as
`kataloop[postgres]`.

## Installation

```sh
pip install kataloop
```

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
