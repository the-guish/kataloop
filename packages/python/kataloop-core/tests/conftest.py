# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""An engine over a fake vendor, a `MemoryStore` and the tools of `support`."""

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx2
import pytest
from uni_llm_client import AsyncClient

from kataloop_core import Kataloop, LocalToolbox, MemoryStore
from support import FakeVendor, Tools


@pytest.fixture
def vendor() -> FakeVendor:
    return FakeVendor()


@pytest.fixture
async def client(vendor: FakeVendor) -> AsyncIterator[AsyncClient]:
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(vendor.handle))
    async with AsyncClient(
        api_keys={"anthropic": "test-key"}, http_client=http, max_retries=0
    ) as client:
        yield client


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def tools() -> Tools:
    return Tools()


@pytest.fixture
def engine(client: AsyncClient, store: MemoryStore, tools: Tools) -> Kataloop:
    return Kataloop(client, store, LocalToolbox(tools.servers()))


@pytest.fixture
async def session(engine: Kataloop) -> UUID:
    session_id = uuid4()
    await engine.create(session_id)
    return session_id
