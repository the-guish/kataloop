# Tools

Status: Draft

## Scope

How the engine offers an agent's tools and runs their calls, as far as the
tools are concerned, and how `McpToolbox`, the `Toolbox` of `kataloop`,
reaches MCP servers: their names, `exclude`, the sessions, the timeouts, what
the model sees of a result and what a failure becomes, on either major of the
MCP SDK. The rounds a turn runs are in [turn.md](turn.md); the contract is
[engine.md](engine.md) (ENG-11).

```python
McpToolbox(*, http_client_factory: HttpClientFactory = ...)

HttpClientFactory = Callable[[dict[str, str], McpHttpTimeout], McpHttpClient]
```

`McpToolbox` reaches each `ToolServer` over the MCP SDK's streamable HTTP
client: its `url`, its `headers` on every request, its `timeout`. The core's
`LocalToolbox` keeps the rules below that are the engine's (TOOLS-1, TOOLS-2,
TOOLS-6) and calls tools of the process's own instead.

The SDK takes the HTTP client it sends with: `streamable_http_client(url,
http_client=...)`. `http_client_factory` makes that client for each session,
from the server's headers and an `McpHttpTimeout` of its timeout, which the
client must send and keep; by default it is a plain `McpHttpClient` with them.
Both are the SDK's HTTP stack's, which differs between its majors (TOOLS-9). It
is the seam for a proxy, for certificates, and for the test server, which
redirects the requests to its mock while keeping their URL.

## Invariants

- **TOOLS-1**: A tool is offered under the name its server gives it; the
  server's `id` names the server to the caller and never reaches the model. A
  name that two of the agent's servers offer is the caller's configuration
  error: the turn raises `ValueError`, naming both servers, before the first
  model call (TURN-2).
- **TOOLS-2**: `exclude` names tools by their server's names. An excluded tool
  is listed by its server but neither offered nor run: a call to it gets the
  error result `There is no tool named 'x'.` A name `exclude` lists that the
  server does not offer is no error, and an excluded name clashes with
  nothing.
- **TOOLS-3**: Each listing and each call opens a session of its own to the
  server, initialises it, sends its one request, and closes the session and its
  HTTP client before it returns, raises or is cancelled. Nothing stays open
  between calls, so the `Toolbox` port has no open and no close, and a
  cancelled turn leaves no session behind (ENG-5). The cost is an initialise
  per call.
- **TOOLS-4**: Every request of a session carries the server's `headers`, the
  credential among them. The HTTP client's connect, read, write and pool
  timeouts and the SDK's wait for each response are the server's `timeout`; the
  engine bounds each call by it as a whole (TURN-6), and each listing by the
  turn's deadline (TURN-8).
- **TOOLS-5**: A listing is every page of the server's `tools/list`, in its
  order: each tool's name, its description (empty when it has none) and its
  input schema as the server gives them. What the model sees of a call is the
  result's content, one part per line: a text part as its text, any other part
  as its JSON under MCP's names, compact and with its keys sorted, so that
  every port writes it alike. A result the server marks `isError` is an
  error result with that text (`ToolOutput.is_error`). Structured content is
  not shown, so it is not checked against the tool's output schema either.
- **TOOLS-6**: A call that fails is an error result and the turn goes on
  (ENG-11): an error response of the server is `The tool call failed:
  MCPError.`, a server out of reach is the transport's error by its type, such
  as `The tool call failed: ConnectError.`, and a call past the server's
  timeout, whether the engine, the SDK or the HTTP client sees it first, is
  `Timed out after N seconds.`, never the SDK's own `Request 'tools/call' timed
  out`. The SDK raises its errors wrapped in exception groups; the toolbox
  raises the error itself. A listing that fails is no tool call: the turn
  raises its error.
- **TOOLS-7**: The headers go to the HTTP client and nowhere else: the toolbox
  writes nothing to a log (ENG-15).
- **TOOLS-8**: `McpToolbox` runs on mcp 1, from 1.30, and on mcp 2, from 2.3:
  `kataloop` depends on `mcp>=1.30,<3`, so a plain install takes the major the
  environment holds, and two extras narrow it, `kataloop[mcp-1]` to mcp 1, for
  an environment that holds a library which needs it, and `kataloop[mcp-2]` to
  mcp 2. The extras conflict: one environment holds one major. When `kataloop`
  is imported, the toolbox takes the major of the `mcp` distribution installed,
  read from its version, and imports nothing of the other's SDK or HTTP stack.
  There is one `McpToolbox`, with the same constructor on both.
- **TOOLS-9**: The HTTP client a factory makes is the one the SDK sends with:
  an `httpx.AsyncClient` on mcp 1, an `httpx2.AsyncClient` on mcp 2.
  `kataloop` exports the class of the major installed as `McpHttpClient`, its
  timeout as `McpHttpTimeout`, and `HttpClientFactory` over the two, so that a
  factory written with them runs on either major without naming it.
- **TOOLS-10**: The rules above hold alike on either major: the same session
  per listing and per call, the server's headers and timeout (TOOLS-3,
  TOOLS-4), the same listing and the same text of a result (TOOLS-5; a
  resource's `uri` aside, under Open questions), the same failures (TOOLS-6).
  An error response of the server is an `MCPError` on both, on mcp 1 a
  subclass of the SDK's `McpError` under mcp 2's name; so is an HTTP error
  status or a redirect the SDK does not follow, which mcp 2 reads as one and
  mcp 1 would raise as `HTTPStatusError`. What differs is the SDK's own: the
  protocol version and client information of the initialise handshake, and
  the HTTP stack's user agent. The language-agnostic tests run the test server
  on each major, against one mock server on mcp 2.

## Non-goals

- Transports other than streamable HTTP: stdio, the legacy SSE transport.
- The rest of MCP: resources, prompts, sampling, elicitation, notifications,
  and the 2026-07-28 protocol's discovery; the toolbox speaks the
  initialise handshake.
- Authorisation flows: the caller resolves the credential into the headers.

## Open questions

- A session per call costs an initialise per call. A session per turn would
  need the `Toolbox` port to open and close it with the turn.
- The SDK logs the messages it sends and receives at DEBUG level, the tools'
  arguments and results among them, though never the headers. A caller that
  turns DEBUG on for the `mcp` loggers sees conversation content in its logs.
- A result with structured content and no content part reaches the model
  empty.
- mcp 1 parses the `uri` of a resource part as a URL and writes it
  normalised, `https://Example.com` as `https://example.com/`, where mcp 2
  keeps the server's text, so the JSON of such a part can differ between the
  majors (TOOLS-10). The toolbox sees the SDK's types only, not the text the
  server sent.
- A type checker cannot see the version installed: mypy reads `McpToolbox` as
  on mcp 2 unless told otherwise (`kataloop`'s README).
