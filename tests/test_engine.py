# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""Runs each case's steps against the test server and compares every request the
mocks receive, and every reply, with the case's payloads (README.md)."""

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import MockMcp, MockVendor, VendorCall, call, same_request

HERE = Path(__file__).parent
PAYLOADS = HERE / "reusable_payloads"
API_KEYS = {"anthropic": "test-key", "openrouter": "test-key"}
OPERATIONS = ("setup", "create", "exists", "stream", "fork", "forget")
SESSION_KEYS = ("session_id", "source_id", "target_id")
CASES = [
    case
    for path in sorted((HERE / "cases").glob("*.json"))
    for case in json.loads(path.read_text())
]
NEW = "a checkpoint id no earlier step returned"


def payload(name: str) -> Any:
    return json.loads((PAYLOADS / f"{name}.json").read_text())


def placed(value: Any, checkpoints: list[str | None], new: str | None = None) -> Any:
    """`value` with each ``{"$checkpoint": N}`` replaced by the checkpoint id of the
    `done` step N returned, and each ``{"$checkpoint": "new"}`` by `new`."""
    if isinstance(value, dict):
        if value.keys() == {"$checkpoint"}:
            step = value["$checkpoint"]
            if step == "new":
                return new if new is not None else NEW
            checkpoint = checkpoints[step]
            if checkpoint is None:
                raise AssertionError(f"step {step} returned no checkpoint")
            return checkpoint
        return {key: placed(item, checkpoints, new) for key, item in value.items()}
    if isinstance(value, list):
        return [placed(item, checkpoints, new) for item in value]
    return value


def minted(reply: dict[str, Any]) -> str | None:
    """The checkpoint id of the reply's `done`, if it has one."""
    for event in reply.get("events", []):
        if event.get("type") == "done":
            checkpoint: str | None = event.get("checkpoint_id")
            return checkpoint
    return None


def arguments_parsed(value: Any) -> Any:
    """`value` with the JSON text under ``arguments`` parsed, since ports format
    that text differently."""
    if isinstance(value, dict):
        return {
            key: json.loads(item)
            if key == "arguments" and isinstance(item, str)
            else arguments_parsed(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [arguments_parsed(item) for item in value]
    return value


def vendor_sent(
    vendor_call: VendorCall, expected: dict[str, Any] | None
) -> dict[str, Any]:
    """The parts of the call that `expected` describes. Its headers are a subset."""
    keys = expected["headers"] if expected else vendor_call.headers
    return {
        "method": vendor_call.method,
        "url": vendor_call.url,
        "headers": {key: vendor_call.headers.get(key) for key in keys},
        "json": arguments_parsed(vendor_call.json),
    }


def mcp_sent(
    calls: list[dict[str, Any]], expected: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Each call as the expected request it matches describes it, its headers a
    subset; a call that matches none, whole."""
    remaining = list(expected)
    views = []
    for mcp_call in calls:
        match = next((e for e in remaining if same_request(e, mcp_call)), None)
        if match is not None:
            remaining.remove(match)
        keys = match["headers"] if match else mcp_call["headers"]
        headers = {key: mcp_call["headers"].get(key) for key in keys}
        views.append({**mcp_call, "headers": headers})
    return views


def in_any_order(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The calls of a round run together, so their order is not compared."""
    return sorted(requests, key=lambda request: json.dumps(request, sort_keys=True))


def without_error_message(reply: dict[str, Any]) -> dict[str, Any]:
    """Error messages differ between ports; only the type is shared."""
    if isinstance(reply.get("error"), dict):
        return {**reply, "error": {"type": reply["error"].get("type")}}
    return reply


def sessions_named(args: dict[str, Any]) -> set[str]:
    return {args[key] for key in SESSION_KEYS if isinstance(args.get(key), str)}


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_runs_the_case(
    implementation: str, vendor: MockVendor, mcp: MockMcp, case: dict[str, Any]
) -> None:
    checkpoints: list[str | None] = []
    sessions: set[str] = set()
    try:
        for number, step in enumerate(case["steps"]):
            (name,) = [key for key in OPERATIONS if key in step]
            exchanges = step.get("vendor", [])
            vendor.serve([payload(exchange["response"]) for exchange in exchanges])
            tool_exchanges = step.get("mcp", [])
            expected_mcp = [payload(exchange["request"]) for exchange in tool_exchanges]
            responses = [payload(exchange["response"]) for exchange in tool_exchanges]
            mcp.serve(list(zip(expected_mcp, responses, strict=True)))

            args = placed(payload(step[name]), checkpoints)
            sessions |= sessions_named(args)
            if name == "stream":
                args = {"api_keys": API_KEYS, **args}
            reply = call(implementation, name, args)

            checkpoint = minted(reply)
            new = checkpoint if checkpoint not in checkpoints else None
            checkpoints.append(checkpoint)

            expected = [
                arguments_parsed(payload(exchange["request"])) for exchange in exchanges
            ]
            # Extra calls are compared whole; missing ones show as a shorter list.
            padded = expected + [None] * (len(vendor.calls) - len(expected))
            calls = [
                vendor_sent(c, e) for c, e in zip(vendor.calls, padded, strict=False)
            ]
            assert calls == expected, f"step {number}: vendor requests"
            assert in_any_order(mcp_sent(mcp.calls, expected_mcp)) == in_any_order(
                expected_mcp
            ), f"step {number}: MCP requests"
            expected_reply = placed(payload(step["reply"]), checkpoints, new)
            assert without_error_message(reply) == expected_reply, (
                f"step {number}: reply"
            )
    finally:
        # The server keeps its memory across cases: each case forgets its own.
        for session in sorted(sessions):
            call(implementation, "forget", {"session_id": session})
