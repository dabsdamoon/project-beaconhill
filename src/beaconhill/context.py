from __future__ import annotations

from typing import TYPE_CHECKING

from beaconhill.models import Message, Role

if TYPE_CHECKING:
    from beaconhill.client import OllamaClient

# Gemma 4 26B default context via Ollama: 32768 tokens
DEFAULT_CONTEXT_LIMIT = 32768
# Fallback estimate when no actual token count is available
CHARS_PER_TOKEN = 4
# Reserve tokens for the model's response
RESPONSE_RESERVE = 1024
# When compacting, keep the system prompt + last N messages intact
KEEP_RECENT = 6


def estimate_tokens(messages: list[Message]) -> int:
    """Estimate total token count for a message list using char-based heuristic."""
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
    client: OllamaClient | None = None,
) -> bool:
    """Check if messages are approaching the context limit.

    Uses actual token count from the last Ollama response when available,
    falling back to character-based estimation.
    """
    usable = context_limit - RESPONSE_RESERVE
    if client and client.last_prompt_tokens > 0:
        return client.last_prompt_tokens > usable
    return estimate_tokens(messages) > usable


def compact_messages(
    messages: list[Message],
    client: "OllamaClient | None",
) -> list[Message]:
    """Compact older messages by summarizing them.

    Keeps: system prompt (first message) + last KEEP_RECENT messages.
    Summarizes everything in between. Uses the LLM for summarization
    when a client is available, otherwise falls back to truncation.
    """
    if len(messages) <= KEEP_RECENT + 2:
        return messages

    system = messages[0] if messages[0].role == Role.SYSTEM else None
    start = 1 if system else 0
    cutoff = len(messages) - KEEP_RECENT
    old_messages = messages[start:cutoff]
    recent = messages[cutoff:]

    if client is not None:
        summary_text = _llm_summarize(old_messages, client)
    else:
        summary_text = _truncation_summarize(old_messages)

    summary_msg = Message(role=Role.ASSISTANT, content=summary_text)

    result = []
    if system:
        result.append(system)
    result.append(summary_msg)
    result.extend(recent)
    return result


def _llm_summarize(messages: list[Message], client: "OllamaClient") -> str:
    """Use the LLM to produce a concise summary of older messages."""
    # Build a condensed transcript of the old conversation
    transcript_parts: list[str] = []
    for m in messages:
        if m.role == Role.USER:
            transcript_parts.append(f"User: {_truncate(m.content or '', 200)}")
        elif m.role == Role.ASSISTANT and m.content:
            transcript_parts.append(f"Assistant: {_truncate(m.content, 200)}")
        elif m.role == Role.ASSISTANT and m.tool_calls:
            names = [tc.name for tc in m.tool_calls]
            transcript_parts.append(f"Assistant used tools: {', '.join(names)}")
        elif m.role == Role.TOOL:
            transcript_parts.append(f"Tool result: {_truncate(m.content or '', 100)}")
    transcript = "\n".join(transcript_parts)

    # Cap the transcript to avoid using too many tokens for the summary itself
    if len(transcript) > 4000:
        transcript = transcript[:4000] + "\n[transcript truncated]"

    summary_prompt = Message(
        role=Role.USER,
        content=(
            "Summarize this conversation history in 3-5 concise bullet points. "
            "Focus on: what the user asked for, what tools were used, what was accomplished, "
            "and any unresolved issues. Be brief.\n\n"
            f"{transcript}"
        ),
    )

    try:
        response = client.chat([summary_prompt])
        summary = response.content or ""
    except Exception:
        # Fall back to truncation if LLM call fails
        return _truncation_summarize(messages)

    return f"[Earlier conversation summary]\n{summary}"


def _truncation_summarize(messages: list[Message]) -> str:
    """Simple truncation-based summary as a fallback."""
    summary_parts: list[str] = []
    for m in messages:
        if m.role == Role.USER:
            summary_parts.append(f"User asked: {_truncate(m.content or '', 100)}")
        elif m.role == Role.ASSISTANT and m.content:
            summary_parts.append(f"Assistant: {_truncate(m.content, 100)}")
        elif m.role == Role.ASSISTANT and m.tool_calls:
            names = [tc.name for tc in m.tool_calls]
            summary_parts.append(f"Assistant used tools: {', '.join(names)}")
    return "[Earlier conversation summary]\n" + "\n".join(summary_parts)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
