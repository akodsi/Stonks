"""
Local LLM client using Apple MLX for inference on Apple Silicon.
Falls back gracefully if MLX or the model is unavailable.
"""
import os
import threading
from typing import Iterator, Optional

MLX_MODEL = os.getenv("MLX_MODEL", "mlx-community/Mistral-7B-Instruct-v0.3-4bit")
OLLAMA_MODEL = MLX_MODEL  # kept for cache table compatibility

DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_P = 0.9
DEFAULT_REPETITION_PENALTY = 1.1

SYSTEM_PROMPT = (
    "You are a sharp buy-side equity analyst writing for a portfolio manager "
    "who values conviction over coverage. Take a clear stance. Back every claim "
    "with a specific number from the data provided. Never invent numbers. "
    "Never use generic phrases like 'well-positioned', 'robust', 'strong "
    "fundamentals', 'market leader', 'innovative', 'mixed signals', or 'time "
    "will tell'. If the data is mixed, say which side of the mix wins and why. "
    "Write tight, specific prose. No hedging."
)

# Lazy-loaded singleton
_model = None
_tokenizer = None
_lock = threading.Lock()
_available = None  # type: Optional[bool]


class OllamaUnavailableError(Exception):
    """Raised when the local LLM is unavailable."""
    pass


def _load_model():
    """Lazy-load the MLX model and tokenizer (one-time)."""
    global _model, _tokenizer
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        try:
            from mlx_lm import load
            print(f"[narrative] Loading MLX model: {MLX_MODEL} ...")
            _model, _tokenizer = load(MLX_MODEL)
            print(f"[narrative] Model loaded successfully.")
        except Exception as e:
            print(f"[narrative] Failed to load MLX model: {e}")
            raise OllamaUnavailableError(f"Failed to load model: {e}")


def is_available() -> bool:
    """Check if MLX and the model can be loaded."""
    global _available
    # Cache positive result permanently; never cache failure so a retry works
    if _available is True:
        return True
    try:
        _load_model()
        _available = True
        return True
    except Exception:
        return False


def _format_prompt(user_prompt: str) -> str:
    """
    Apply the tokenizer's chat template so the instruction-tuned model receives
    properly formatted system+user turns. Falls back to raw prompt if the
    tokenizer lacks a chat template.
    """
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        return _tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
    except Exception:
        # Some tokenizers (or Mistral variants) don't support a system role.
        # Merge system into user turn as a fallback.
        try:
            messages = [
                {"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{user_prompt}"},
            ]
            return _tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        except Exception:
            return f"{SYSTEM_PROMPT}\n\n{user_prompt}"


def _build_sampler_kwargs(temperature: float):
    """Build sampler + logits_processors kwargs for mlx_lm generate/stream."""
    from mlx_lm.sample_utils import make_sampler, make_logits_processors

    sampler = make_sampler(temp=temperature, top_p=DEFAULT_TOP_P)
    logits_processors = make_logits_processors(
        repetition_penalty=DEFAULT_REPETITION_PENALTY
    )
    return {"sampler": sampler, "logits_processors": logits_processors}


def generate(
    prompt: str,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """Blocking call. Returns the full response text."""
    try:
        _load_model()
        from mlx_lm import generate as mlx_generate
        formatted = _format_prompt(prompt)
        return mlx_generate(
            _model,
            _tokenizer,
            prompt=formatted,
            max_tokens=max_tokens,
            **_build_sampler_kwargs(temperature),
        )
    except OllamaUnavailableError:
        raise
    except Exception as e:
        raise OllamaUnavailableError(f"Generation error: {e}")


def generate_stream(
    prompt: str,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Iterator[str]:
    """Streaming call. Yields text chunks as they are generated."""
    try:
        _load_model()
        from mlx_lm import stream_generate
        formatted = _format_prompt(prompt)
        for response in stream_generate(
            _model,
            _tokenizer,
            prompt=formatted,
            max_tokens=max_tokens,
            **_build_sampler_kwargs(temperature),
        ):
            text = response.text if hasattr(response, "text") else str(response)
            if text:
                yield text
    except OllamaUnavailableError:
        raise
    except Exception as e:
        raise OllamaUnavailableError(f"Stream error: {e}")
