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

A turn of an agent with one tool of the process's own, its memory kept in the
process:

```python
import asyncio
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from kataloop import (
    AgentDefinition,
    Done,
    Kataloop,
    LocalToolbox,
    MemoryStore,
    ModelSpec,
    TextDelta,
    ToolServer,
    ToolSpec,
)
from uni_llm_client import AsyncClient


async def forecast(arguments: Mapping[str, Any]) -> str:
    return f"Sunny in {arguments['city']}."


CITY = {"type": "object", "properties": {"city": {"type": "string"}}}
TOOLS = LocalToolbox(
    {"weather": [(ToolSpec("forecast", "The forecast for a city.", CITY), forecast)]}
)
AGENT = AgentDefinition("Answer briefly.", (ToolServer("weather", "local"),))
MODEL = ModelSpec("anthropic/<model>")  # a uni-llm-client model id


async def main() -> None:
    async with AsyncClient() as client:  # the key from ANTHROPIC_API_KEY
        engine = Kataloop(client, MemoryStore(), TOOLS)
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

The model calls `forecast`, the tool's own name on its server. Each turn goes
on from the checkpoint the previous one ended with. The
engine and its turns are specified in
[docs/specs](https://github.com/the-guish/kataloop/tree/main/docs/specs).

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
