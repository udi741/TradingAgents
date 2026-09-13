# Devin Bridge — Local Sidecar for TradingAgents

The Devin bridge is a local HTTP server that lets TradingAgents use your
authenticated Devin CLI instead of a direct LLM-provider API key. It speaks
the OpenAI Chat Completions API, so TradingAgents points its existing
`openai_compatible` provider at it with no source changes.

## Quick start

### Terminal 1: Start the bridge

```bash
cd /home/udi/udi_provate/TradingAgents
. .venv/bin/activate
python -m devin_bridge
```

This uses **GLM-5.2 High** (`glm-5-2`) for both quick and deep analysis.

Verify it's running:

```bash
curl http://127.0.0.1:8765/healthz
# {"status": "ok", "models": {"devin-quick": "glm-5-2", "devin-deep": "glm-5-2"}, "runtime_ready": true}
```

### Terminal 2: Run TradingAgents

```bash
cd /home/udi/udi_provate/TradingAgents
. .venv/bin/activate

export TRADINGAGENTS_LLM_PROVIDER=openai_compatible
export TRADINGAGENTS_LLM_BACKEND_URL=http://127.0.0.1:8765/v1
export TRADINGAGENTS_DEEP_THINK_LLM=devin-deep
export TRADINGAGENTS_QUICK_THINK_LLM=devin-quick

tradingagents
```

Or from source:

```bash
python -m cli.main
```

### Stop the bridge

In Terminal 1, press `Ctrl+C`.

## Choosing models

By default, both `devin-quick` and `devin-deep` use **GLM-5.2 High**
(`glm-5-2`).

### See available models

```bash
python -m devin_bridge --list-models
```

This queries the authenticated Devin CLI (no inference) and prints every
available model with its display name and CLI identifier.

### Use one model for everything

```bash
python -m devin_bridge --model <model-id>
```

Sets both quick and deep to the same model.

### Use separate models for quick and deep

```bash
python -m devin_bridge \
  --quick-model <fast-model-id> \
  --deep-model <strong-model-id>
```

### Precedence

1. `--quick-model` / `--deep-model` (explicit per-alias)
2. `--model` (sets both)
3. `DEVIN_BRIDGE_QUICK_MODEL` / `DEVIN_BRIDGE_DEEP_MODEL` env vars
4. `DEVIN_BRIDGE_MODEL` env var
5. Default: `glm-5-2` (GLM-5.2 High)

At startup, the bridge validates both configured models against the models
available from your authenticated Devin CLI. If a model is unavailable, the
bridge refuses to start and names the invalid model.

## Configuration

### Bridge options

```bash
python -m devin_bridge --help
```

| Option | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Bind host (loopback only by default) |
| `--port` | `8765` | Bind port |
| `--model` | `glm-5-2` | Devin model for BOTH quick and deep (shorthand) |
| `--quick-model` | `glm-5-2` | Devin model for `devin-quick` (overrides `--model`) |
| `--deep-model` | `glm-5-2` | Devin model for `devin-deep` (overrides `--model`) |
| `--timeout` | `180` | Per-request Devin timeout (seconds) |
| `--max-concurrency` | `1` | Max concurrent Devin invocations |
| `--runtime-dir` | auto | Devin runtime workspace (outside checkout) |
| `--export-dir` | none | Directory for Devin export files |
| `--devin-bin` | auto | Path to Devin CLI binary |
| `--debug` | off | Enable debug logging |
| `--list-models` | — | List available Devin models and exit |

### TradingAgents environment variables

| Variable | Value |
|---|---|
| `TRADINGAGENTS_LLM_PROVIDER` | `openai_compatible` |
| `TRADINGAGENTS_LLM_BACKEND_URL` | `http://127.0.0.1:8765/v1` |
| `TRADINGAGENTS_DEEP_THINK_LLM` | `devin-deep` |
| `TRADINGAGENTS_QUICK_THINK_LLM` | `devin-quick` |

### Bridge environment variables (optional)

| Variable | Description |
|---|---|
| `DEVIN_BRIDGE_MODEL` | Devin model for both quick and deep |
| `DEVIN_BRIDGE_QUICK_MODEL` | Devin model for `devin-quick` only |
| `DEVIN_BRIDGE_DEEP_MODEL` | Devin model for `devin-deep` only |

No external LLM-provider API key is required. The bridge uses your
authenticated Devin CLI session.

## Model aliases

The bridge accepts these model names from TradingAgents:

- `devin-quick` → maps to the configured quick model (default: `glm-5-2`)
- `devin-deep` → maps to the configured deep model (default: `glm-5-2`)

Both map to **GLM-5.2 High** by default. Use `--quick-model` and
`--deep-model` to set them independently.

## How it works

1. TradingAgents sends an OpenAI Chat Completions request to the bridge.
2. The bridge serializes the messages and tools into a prompt file.
3. The bridge invokes `devin -p --prompt-file <file>` in an isolated runtime
   workspace.
4. Devin responds with a JSON envelope wrapped in sentinel markers.
5. The bridge validates the envelope and translates it to an OpenAI
   Chat Completions response.
6. TradingAgents receives the response through its existing
   `LocalCompatibleChatOpenAI` client.

Each request is a fresh Devin invocation. No session continuation is used.

## Runtime isolation

The bridge creates a disposable runtime workspace **outside** the TradingAgents
checkout, under the OS temp location (e.g.
`/tmp/tradingagents-devin-bridge-<unique>/`). This directory is automatically
cleaned up when the bridge shuts down gracefully.

The runtime workspace contains restrictive permissions that deny Devin's
native coding tools (shell, file access, web fetch, MCP). This ensures Devin
acts only as a model.

If you supply `--runtime-dir` explicitly, the bridge verifies the path is
**outside** the TradingAgents checkout (using real-path resolution to handle
`..` and symlinks) and will refuse to start if it resolves inside the
checkout. User-supplied runtime directories are NOT deleted on shutdown —
only auto-created temp directories are cleaned up.

## Limitations

- No streaming (requests with `stream=true` are rejected)
- No token usage tracking (reports 0 tokens)
- Devin prompt-framing sensitivity (the bridge uses a natural formatting task
  framing to avoid triggering prompt-injection detection)
- `Fetch(*)` catch-all and read/grep/glob denial not independently live-proven
