# Gemini Troubleshooting

Use this when the Gemini extension is installed but the `seedcore.*` tools do not work.

## Extension installed but tools unavailable

- Run `/extensions list` and confirm `seedcore` is installed.
- If the extension is present but no `seedcore.*` tools appear, the local MCP launcher likely failed to start.

## `python` cannot import `seedcore`

- Gemini launches the Seedcore MCP server with `python`.
- Run Gemini from the repository's activated Python environment so Seedcore dependencies are importable.
- A quick check from the repo root is:

```bash
python -c "import seedcore; print(seedcore.__file__)"
```

## MCP dependency missing

- The Gemini launcher needs the Python `mcp` package available in the active environment.
- Verify with:

```bash
python -c "from mcp.server.fastmcp import FastMCP; print(FastMCP)"
```

## Seedcore API not reachable

- The Gemini extension does not start the Seedcore runtime for you.
- Verify the local runtime separately:

```bash
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8002/readyz
```

- If needed, use the host-mode startup steps in `deploy/local/README.md`.
