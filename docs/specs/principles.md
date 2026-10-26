# Principles

kataloop runs an agent's turns: it asks a model, runs the tools the model asks
for, gives the results back, and goes on until the model answers. It streams
what happens and remembers the conversation. It reaches the vendors through
uni-llm-client and nothing else.

The engine is standalone. robinauts is one caller; a script, a job or another
platform can be another. Everything a caller needs crosses one contract,
[engine.md](engine.md), in the caller's terms: no vendor SDK type, no framework
object.

The Python port is two packages. `kataloop-core` has the contract, the loop,
the context management and memory kept in the process; it depends on
uni-llm-client and nothing else. `kataloop` is the package a caller installs:
it re-exports the core and adds what needs a dependency, each behind one of the
core's ports: MCP tool servers through the `Toolbox` port, and PostgreSQL
memory through the `Store` port as `kataloop[postgres]`. The core alone runs
with tools of the process's own and memory that lasts as long as the process.

The core never writes its own MCP client. Reaching tool servers is the MCP
SDK's job, in `kataloop`.

Every port of kataloop, in every language, passes the language-agnostic tests
in `tests`, through a test server that exposes the engine over HTTP. The test
server is test code: it lives in the port's `tests` directory and ships in no
package.

The engine keeps secrets secret: it never writes a key, a secret or
conversation content to a log, and it sends nothing anywhere but to the model
providers and the tool servers it is given.
