# Language-agnostic tests

Status: Planned (step 4 of [docs/plan.md](../docs/plan.md)). Nothing runs yet.

These tests check that every port runs a turn the same way: the same requests
to the model vendor and the tool servers, the same events back. Each port
ships a test server that exposes the engine over HTTP. The tests start a mock
vendor and a mock MCP server, start the port's test server, and drive it
through a case. The mocks record each request they receive, and each test
compares those requests, and the test server's replies, with the case's
payloads, as uni-llm-client's tests do.

The test server is test code. It lives in the port's `tests` directory, next to
its packages and outside them, and ships in no package.

## Test server protocol

The runner starts the `command` of `implementations.json` in `cwd`, relative
to the repository root, and appends `--vendor-url URL` and `--mcp-url URL`.

1. The server listens on a free port of `127.0.0.1`. Its first line on stdout
   is `listening on http://127.0.0.1:PORT`.
2. The server sends every vendor request to the vendor URL, keeping the
   vendor's path and `Host` header, and every tool server request to the MCP
   URL the same way.
3. The operations of the engine are `POST /setup`, `/create`, `/exists`,
   `/stream`, `/fork` and `/forget`, each taking the operation's arguments as
   a JSON object. `/stream` reads the whole turn and replies
   `{"events": [EVENT, ...]}`; an error during the turn replies the events so
   far, plus `error`. The other operations reply their result, or
   `{"error": {"type": "...", "message": "..."}}` for an error of the contract.
4. The server keeps one engine for its lifetime, over memory in the process,
   so that a case's steps share sessions and checkpoints.
5. Any other failure replies with status 500. Its body helps debugging.

The JSON forms of the values and events follow
[docs/specs/engine.md](../docs/specs/engine.md); messages and responses inside
them take uni-llm-client's JSON form.
