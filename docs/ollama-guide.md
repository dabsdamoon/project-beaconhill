# Ollama Quick Reference

Ollama is the inference server that loads and runs LLM models locally. On Apple Silicon, it uses the MLX framework for GPU-accelerated inference via Metal.

## Installation

```bash
brew install ollama
```

This installs Ollama along with MLX dependencies. No CUDA or separate GPU drivers needed.

## Starting & Stopping

```bash
# Run as a background service (auto-starts on login)
brew services start ollama

# Stop the background service
brew services stop ollama

# Or run manually in the foreground (with recommended optimizations)
OLLAMA_FLASH_ATTENTION="1" OLLAMA_KV_CACHE_TYPE="q8_0" ollama serve
```

## Model Management

```bash
# Download a model
ollama pull gemma4:26b

# List downloaded models
ollama list

# Show model details
ollama show gemma4:26b

# Remove a model (frees disk space)
ollama rm gemma4:26b

# Check what's currently loaded in memory
ollama ps
```

## Interactive Chat

```bash
ollama run gemma4:26b
```

Type messages directly. Press Ctrl+D to exit.

## API Usage

Ollama exposes an OpenAI-compatible REST API at `http://localhost:11434`.

### Chat Completion

```bash
curl http://localhost:11434/api/chat -d '{
  "model": "gemma4:26b",
  "messages": [
    {"role": "user", "content": "Hello, what are you?"}
  ],
  "stream": false
}'
```

### Streaming Chat

```bash
curl http://localhost:11434/api/chat -d '{
  "model": "gemma4:26b",
  "messages": [
    {"role": "user", "content": "Explain recursion briefly."}
  ],
  "stream": true
}'
```

Each line of the streamed response is a JSON object with a `message` field containing the incremental content.

### OpenAI-Compatible Endpoint

Ollama also serves an OpenAI-compatible endpoint for drop-in compatibility with existing tools:

```bash
curl http://localhost:11434/v1/chat/completions -d '{
  "model": "gemma4:26b",
  "messages": [
    {"role": "user", "content": "Hello"}
  ]
}'
```

### Python Example

```python
import httpx

response = httpx.post(
    "http://localhost:11434/api/chat",
    json={
        "model": "gemma4:26b",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": False,
    },
)
print(response.json()["message"]["content"])
```

## Memory Behavior

| State | RAM Usage | Battery Impact |
|-------|-----------|----------------|
| Ollama server only (no model loaded) | ~95 MB | Negligible |
| Model loaded, idle | ~19 GB | Moderate |
| Model loaded, generating | ~19 GB + KV cache | High (GPU active) |
| Model auto-unloaded (after ~5 min idle) | ~95 MB | Negligible |

Ollama automatically unloads the model from memory after approximately 5 minutes of inactivity. The next request triggers a reload (takes a few seconds).

## Useful Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `OLLAMA_HOST` | Change bind address/port | `0.0.0.0:11434` |
| `OLLAMA_MODELS` | Custom model storage path | `/path/to/models` |
| `OLLAMA_FLASH_ATTENTION` | Enable flash attention | `1` |
| `OLLAMA_KV_CACHE_TYPE` | KV cache quantization | `q8_0` |
| `OLLAMA_NUM_PARALLEL` | Max parallel requests | `2` |
| `OLLAMA_MAX_LOADED_MODELS` | Max models in memory | `1` |
| `OLLAMA_KEEP_ALIVE` | Time before auto-unload | `5m` (default) |

## Offline Usage

Once a model is pulled, Ollama works entirely offline. No internet required for:
- Starting the server
- Loading models
- Running inference
- API calls

Internet is only needed for `ollama pull` (downloading model weights).

## Troubleshooting

```bash
# Check if server is running
curl http://localhost:11434/api/tags

# Check server logs
brew services info ollama

# Restart if unresponsive
brew services restart ollama
```
