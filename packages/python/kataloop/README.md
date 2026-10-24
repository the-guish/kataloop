# kataloop

A small agent loop: it asks a model, runs the tools the model asks for over
MCP, gives the results back, and goes on until the model answers, streaming
what happens and remembering the conversation. It reaches the vendors through
uni-llm-client.

This package re-exports [`kataloop-core`](https://pypi.org/project/kataloop-core/)
and adds what needs a dependency: MCP tool servers, and PostgreSQL memory as
`kataloop[postgres]`.

## Installation

`McpToolbox` reaches MCP servers through the MCP SDK, `mcp`, on either of its
majors. Install `kataloop` with the extra that names one:

```sh
pip install "kataloop[mcp-2]"
pip install "kataloop[mcp-1]"
```

- `mcp-2`, for mcp 2.3 or later: the one to pick unless something in the
  environment needs mcp 1;
- `mcp-1`, for mcp 1.30 or later, beside a library that needs mcp 1, such as
  `langchain-mcp-adapters`.

The two extras cannot be installed together. A plain `pip install kataloop`
takes whichever major the environment holds or resolves to; the toolbox picks
the major installed when `kataloop` is imported.

## Usage

A turn of an agent with the tools of an MCP server, its memory kept in the
process:

```python
import asyncio
from uuid import uuid4

from kataloop import (
    AgentDefinition,
    Done,
    Kataloop,
    McpToolbox,
    MemoryStore,
    ModelSpec,
    TextDelta,
    ToolServer,
)
from uni_llm_client import AsyncClient

WEATHER = ToolServer(
    "weather",
    "https://weather.example.com/mcp",
    headers={"Authorization": "Bearer <token>"},  # resolved by the caller
    timeout=30,
)
AGENT = AgentDefinition("Answer briefly.", (WEATHER,))
MODEL = ModelSpec("anthropic/<model>")  # a uni-llm-client model id


async def main() -> None:
    async with AsyncClient() as client:  # the key from ANTHROPIC_API_KEY
        engine = Kataloop(client, MemoryStore(), McpToolbox())
        session = uuid4()
        await engine.create(session)
        last = None
        for prompt in ["What is the weather in Paris?", "And in Rome?"]:
            turn = engine.stream(
                session, AGENT, prompt, model=MODEL, checkpoint_id=last, timeout=120
            )
            async for event in turn:
                if isinstance(event, TextDelta):
                    print(event.text, end="", flush=True)
                elif isinstance(event, Done):
                    last = event.checkpoint_id
            print()


asyncio.run(main())
```

The model is offered the server's tools under their own names, and each call
opens a session to the server and closes it when the call ends. Each turn goes
on from the checkpoint the previous one ended with.

`McpToolbox` takes an `http_client_factory` that makes the HTTP client of each
session from the server's headers and timeout, for a proxy or certificates of
the caller's. The client is the one the SDK sends with, an `httpx.AsyncClient`
on mcp 1 and an `httpx2.AsyncClient` on mcp 2; `McpHttpClient` and
`McpHttpTimeout` are those of the major installed, so a factory written with
them runs on either:

```python
from kataloop import McpHttpClient, McpHttpTimeout, McpToolbox


def through_proxy(headers: dict[str, str], timeout: McpHttpTimeout) -> McpHttpClient:
    return McpHttpClient(headers=headers, timeout=timeout, proxy="http://proxy:3128")


toolbox = McpToolbox(http_client_factory=through_proxy)
```

A type checker cannot see which major is installed, and mypy reads the toolbox
as on mcp 2. On mcp 1, a factory typed with httpx's own classes needs
`always_false = ["MCP_2"]` in the mypy configuration; one written with
`McpHttpClient` and `McpHttpTimeout` type-checks either way.

`LocalToolbox` runs tools of the process's own instead, as in
[`kataloop-core`](https://pypi.org/project/kataloop-core/). The engine and its
turns are specified in
[docs/specs](https://github.com/the-guish/kataloop/tree/main/docs/specs).

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
