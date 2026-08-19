"""One chat function, provider picked by whichever key is set.
Anthropic first, then OpenAI, then OpenRouter."""

import json
import os
import re
import time


def provider():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    if os.environ.get("NVIDIA_API_KEY"):
        return "nvidia"
    raise RuntimeError(
        "no LLM key found, set ANTHROPIC_API_KEY, OPENAI_API_KEY, "
        "OPENROUTER_API_KEY or NVIDIA_API_KEY"
    )


DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4o-mini",
    "openrouter": "anthropic/claude-sonnet-4.5",
    "nvidia": "meta/llama-3.3-70b-instruct",
}


def chat(system, user, max_tokens=2000):
    prov = provider()
    model = os.environ.get("ENGRAM_MODEL", DEFAULT_MODELS[prov])

    if prov == "anthropic":
        import anthropic

        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text

    from openai import OpenAI

    from openai import (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )

    kwargs = {"timeout": 90.0, "max_retries": 0}
    if prov == "openrouter":
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"], **kwargs,
        )
    elif prov == "nvidia":
        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=os.environ["NVIDIA_API_KEY"], **kwargs,
        )
    else:
        client = OpenAI(**kwargs)

    last = None
    for attempt in range(5):
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return resp.choices[0].message.content
        except (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError) as e:
            # free tiers rate limit and queue hard, back off and retry
            last = e
            time.sleep(8 * (attempt + 1))
    raise last


def _extract_json(text):
    # strip a ```json fence if the model added one
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1)
    start = min(
        (i for i in (text.find("{"), text.find("[")) if i != -1), default=0
    )
    # raw_decode tolerates prose after the json, models love adding that
    value, _ = json.JSONDecoder().raw_decode(text[start:].strip())
    return value


def chat_json(system, user, max_tokens=2000):
    """Same as chat but the reply must be a json object or array."""
    try:
        return _extract_json(chat(system, user, max_tokens=max_tokens))
    except (json.JSONDecodeError, ValueError):
        retry = user + "\n\nReturn ONLY valid json, nothing else."
        return _extract_json(chat(system, retry, max_tokens=max_tokens))
