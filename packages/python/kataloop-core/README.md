# kataloop-core

The contract, the loop and in-process memory of
[kataloop](https://github.com/the-guish/kataloop), a small agent loop over
uni-llm-client. It depends on uni-llm-client and nothing else.

Most callers want [`kataloop`](https://pypi.org/project/kataloop/), which
re-exports this package and adds MCP tool servers and PostgreSQL memory.

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
