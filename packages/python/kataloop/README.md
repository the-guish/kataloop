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
on from the checkpoint the previous one ended with. `McpToolbox` takes an
`http_client_factory` that makes the `httpx2.AsyncClient` of each session from
the server's headers and timeout, for a proxy or certificates of the caller's.

`LocalToolbox` runs tools of the process's own instead, as in
[`kataloop-core`](https://pypi.org/project/kataloop-core/). The engine and its
turns are specified in
[docs/specs](https://github.com/the-guish/kataloop/tree/main/docs/specs).

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
