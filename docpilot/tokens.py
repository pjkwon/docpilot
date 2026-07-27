from __future__ import annotations

_TOKENS_PER_BYTE = 0.4


def estimate_tokens_raw(text: str) -> int:
    """Rough token estimate for text sent to an LLM in full — ~0.4 tokens/byte, tuned for
    Korean/mixed text. No tokenizer call, so this is a heuristic (±30%), not an exact count;
    exact counts require the model's own tokenizer, which local models (Ollama) don't expose
    over the API."""
    return int(len(text.encode("utf-8")) * _TOKENS_PER_BYTE)
