from collections import Counter
from threading import Lock

from langchain_core.callbacks import BaseCallbackHandler


def provider_call_metrics(calls: list[dict]) -> dict:
    attempts = [call for call in calls if call.get("layer") == "router"]
    call_ids = {call.get("call_id") for call in attempts}
    logical_count = len(call_ids - {None}) + sum(not call.get("call_id") for call in attempts)
    by_source, by_method = {}, {}
    for call in attempts:
        source = call.get("source", "unknown")
        method = call.get("method", "unknown")
        by_source[source] = by_source.get(source, 0) + 1
        by_method[method] = by_method.get(method, 0) + 1
    cache_calls = [call for call in calls if isinstance(call.get("cache"), dict)]
    return {
        "logical_data_calls": logical_count,
        "provider_attempts": len(attempts),
        "by_source": by_source,
        "by_method": by_method,
        "cache_hits": sum(call["cache"].get("hit") is True for call in cache_calls),
        "external_network_calls": sum(
            call["cache"].get("hit") is False for call in cache_calls
        ) or None,
        "external_network_quality": "PARTIAL" if cache_calls else "UNAVAILABLE",
    }


class ModelCallMetrics(BaseCallbackHandler):
    def __init__(self, model_names: dict[str, str]):
        self.model_names = model_names
        self.calls = Counter()
        self.tokens_in = 0
        self.tokens_out = 0
        self.usage_count = 0
        self.lock = Lock()

    def on_llm_start(self, serialized, prompts, *, invocation_params=None, **kwargs):
        params = invocation_params or {}
        model = params.get("model") or params.get("model_name")
        if not model and isinstance(serialized, dict):
            model = (serialized.get("kwargs") or {}).get("model_name")
        with self.lock:
            self.calls[model or "unknown"] += 1

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.on_llm_start(serialized, messages, **kwargs)

    def on_llm_end(self, response, **kwargs):
        try:
            generation = response.generations[0][0]
            message = getattr(generation, "message", None)
            usage = getattr(message, "usage_metadata", None) or {}
            metadata = getattr(message, "response_metadata", None) or {}
            raw = metadata.get("token_usage") or metadata.get("usage") or {}
            input_tokens = usage.get("input_tokens", raw.get("prompt_tokens", raw.get("input_tokens")))
            output_tokens = usage.get("output_tokens", raw.get("completion_tokens", raw.get("output_tokens")))
            if input_tokens is None or output_tokens is None:
                return
            if int(input_tokens) == 0 and int(output_tokens) == 0:
                return
            with self.lock:
                self.tokens_in += int(input_tokens)
                self.tokens_out += int(output_tokens)
                self.usage_count += 1
        except Exception:
            return

    def snapshot(self) -> dict:
        with self.lock:
            by_model = dict(self.calls)
            names = {
                "quick": self.model_names.get("quick"),
                "deep": self.model_names.get("deep"),
            }
            quick = by_model.get(names["quick"], 0) if names["quick"] else 0
            deep = by_model.get(names["deep"], 0) if names["deep"] else 0
            total = sum(by_model.values())
            if not self.usage_count:
                availability, input_tokens, output_tokens = "UNAVAILABLE", None, None
            else:
                availability = "EXACT" if self.usage_count == total else "PARTIAL"
                input_tokens, output_tokens = self.tokens_in, self.tokens_out
            return {
                "model_calls": {
                    "total": total, "quick": quick, "deep": deep,
                    "by_model": by_model, "counting": "LANGCHAIN_INVOCATION_CALLBACK",
                },
                "tokens": {
                    "availability": availability,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": (
                        input_tokens + output_tokens if input_tokens is not None else None
                    ),
                    "source": "LLM_RESPONSE_USAGE_METADATA",
                },
            }
