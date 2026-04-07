# Model Selection: Gemma 4 26B MoE

## Why This Model

Beaconhill requires a model that balances reasoning quality, inference speed, and memory footprint — all running locally on a MacBook Pro M5 with 32 GB unified memory.

After evaluating available options in April 2026, **Gemma 4 26B-A4B (MoE)** was selected.

## Model Specs

| Property | Value |
|----------|-------|
| Full name | google/gemma-4-26b-a4b-it |
| Architecture | Transformer + Mixture-of-Experts |
| Total parameters | 26 billion |
| Active parameters | 3.8 billion (per inference) |
| Context window | 256K tokens |
| Quantization used | Q4_K_M (default Ollama) |
| Disk size | ~17 GB |
| RAM when loaded | ~19 GB |
| License | Apache 2.0 |
| Release date | April 2, 2026 |

## Why MoE Matters

Mixture-of-Experts routes each token through only a subset of the model's parameters. For Gemma 4 26B:

- 26B total parameters provide the knowledge capacity of a large model
- Only 3.8B are active per token, giving inference speed comparable to an 8B model
- This means near-30B quality at 8B-class speed and memory bandwidth

On the M5 with 32 GB, this leaves ~13 GB free for the OS, the harness process, Ollama server overhead, and KV cache.

## Alternatives Considered

| Model | Total Params | RAM (Q4) | Verdict |
|-------|-------------|----------|---------|
| Gemma 4 E2B | 5.1B (2.3B active) | ~1.5 GB | Too small for reliable tool-use reasoning |
| Gemma 4 E4B | 4B | ~3 GB | Lightweight but limited code understanding |
| **Gemma 4 26B MoE** | **26B (3.8B active)** | **~19 GB** | **Best quality-to-resource ratio** |
| Gemma 4 31B Dense | 30.7B | ~20 GB | Slightly better quality but slower, tighter on RAM |
| Qwen 3 14B | 14B | ~9 GB | Good alternative; dense model, less headroom for context |
| Llama 3.3 8B | 8B | ~5 GB | Fast but weaker reasoning for complex tool-use |
| Gemma 4 31B NVFP4 (NVIDIA) | 30.7B | N/A | Requires NVIDIA GPU (CUDA); incompatible with Apple Silicon |

## Gemma 4 31B NVIDIA NVFP4 — Why Not

NVIDIA released a quantized variant (`nvidia/Gemma-4-31B-IT-NVFP4`) using their proprietary NVFP4 4-bit format. It achieves less than 0.5% accuracy loss across benchmarks. However:

- NVFP4 requires NVIDIA tensor cores (Hopper/Blackwell architecture)
- Inference only supported via vLLM with `--quantization modelopt`
- Completely incompatible with Apple Silicon / Metal / MLX
- Not usable for this project

## Performance Expectations

On Apple M5 (32 GB) with Ollama + MLX backend:

| Metric | Expected |
|--------|----------|
| Token generation speed | ~15-20 tok/s |
| Time to first token | ~2-4 seconds |
| Context window usable | 32K-64K tokens comfortably |
| Concurrent with other apps | Yes, with ~13 GB headroom |

## Ollama Tag

```bash
ollama pull gemma4:26b
ollama run gemma4:26b
```

## Key Strengths for Agent Use

1. **Agentic design**: Google specifically optimized Gemma 4 for edge agentic workloads
2. **Tool-use training**: The instruction-tuned variant has function calling capabilities
3. **Code understanding**: Strong performance on LiveCodeBench and coding benchmarks
4. **Large context**: 256K window supports reading entire files and long conversation histories
5. **Apache 2.0**: No licensing restrictions for any deployment scenario
