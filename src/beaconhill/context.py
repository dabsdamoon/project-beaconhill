from __future__ import annotations

from beaconhill.models import Message, Role

# Gemma 4 26B default context: 8192 tokens via Ollama
# Use conservative estimate: ~4 chars per token
DEFAULT_CONTEXT_LIMIT = 8192
CHARS_PER_TOKEN = 4
# Reserve tokens for the model's response
RESPONSE_RESERVE = 1024
# When compacting, keep the system prompt + last N messages intact
KEEP_RECENT = 6


def estimate_tokens(messages: list[Message]) -> int:
    """Estimate total token count for a message list."""
    total_chars = 0
    for m in messages:
        if m.content:
            total_chars += len(m.content)
        if m.tool_calls:
            for tc in m.tool_calls:
                total_chars += len(tc.name) + len(str(tc.arguments))
    return total_chars // CHARS_PER_TOKEN


def needs_compaction(
    messages: list[Message],
    context_limit: int = DEFAULT_CONTEXT_LIMIT,
) -> bool:
    """Check if messages are approaching the context limit."""
    usable = context_limit - RESPONSE_RESERVE
    return estimate_tokens(messages) > usable


def compact_messages(
    messages: list[Message],
    client: "OllamaClient",
) -> list[Message]:
    """Compact older messages by summarizing them.

    Keeps: system prompt (first message) + last KEEP_RECENT messages.
    Summarizes everything in between into a single assistant message.
    """
    if len(messages) <= KEEP_RECENT + 2:
        return messages

    system = messages[0] if messages[0].role == Role.SYSTEM else None
    start = 1 if system else 0
    cutoff = len(messages) - KEEP_RECENT
    old_messages = messages[start:cutoff]
    recent = messages[cutoff:]

    # Build a summary of the old messages
    summary_parts: list[str] = []
    for m in old_messages:
        if m.role == Role.USER:
            summary_parts.append(f"User asked: {_truncate(m.content or '', 100)}")
        elif m.role == Role.ASSISTANT and m.content:
            summary_parts.append(f"Assistant: {_truncate(m.content, 100)}")
        elif m.role == Role.ASSISTANT and m.tool_calls:
            names = [tc.name for tc in m.tool_calls]
            summary_parts.append(f"Assistant used tools: {', '.join(names)}")

    summary_text = (
        "[Earlier conversation summary]\n"
        + "\n".join(summary_parts)
    )
    summary_msg = Message(role=Role.ASSISTANT, content=summary_text)

    result = []
    if system:
        result.append(system)
    result.append(summary_msg)
    result.extend(recent)
    return result


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
