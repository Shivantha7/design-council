"""Anthropic implementation of the ModelClient protocol.

This is the only module in the project that imports a provider SDK. Everything
upstream of it — the agents, the run logger, the gate — sees the ModelClient
protocol and nothing more, which is what lets the whole experiment be tested
against MockClient without touching the network.

Sampling note. On claude-sonnet-5 the temperature, top_p and top_k parameters
were removed from the API and are rejected with a 400. The model samples at its
own default, which is the variance the consistency measure relies on; there is
simply no parameter to set. sampling_params() therefore reports only what was
actually sent — the absence of a temperature key means default sampling, not an
oversight.
"""

from typing import Any

import anthropic

DEFAULT_MAX_TOKENS = 8000


class AnthropicClient:
    """A ModelClient backed by the Anthropic Messages API."""

    def __init__(
        self,
        requested_model: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        api_key: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.requested_model = requested_model
        self.max_tokens = max_tokens
        self.last_thinking_tokens: int | None = None
        self._client = (
            anthropic.Anthropic() if api_key is None else anthropic.Anthropic(api_key=api_key)
        )
        if timeout is not None:
            self._client = self._client.with_options(timeout=timeout)

    def sampling_params(self) -> dict[str, Any]:
        """Exactly the sampling settings this client sends, for the run record."""
        return {"max_tokens": self.max_tokens}

    def complete(self, prompt: str, **params: Any) -> tuple[str, int, int, str]:
        """Return (text, input_tokens, output_tokens, resolved_model).

        resolved_model comes from the response rather than the request: it is
        what the provider says it used, which is the value the run logger
        enforces for the rest of the run.
        """
        model = params.pop("model", None) or self.requested_model
        max_tokens = params.pop("max_tokens", None) or self.max_tokens

        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            **params,
        )

        # Adaptive thinking is on by default on this model family, so the
        # content list can hold thinking blocks as well as text. Only text
        # blocks carry the answer.
        text = "".join(
            block.text for block in response.content if block.type == "text"
        )

        # Reasoning tokens are part of output_tokens, not additional to them.
        # Recorded separately so a short completion with a large billed output
        # is explicable rather than mysterious. Read off the side of the client
        # because the ModelClient protocol returns a four-tuple, and widening
        # it for one provider's detail would push provider specifics into every
        # caller and every mock.
        details = getattr(response.usage, "output_tokens_details", None)
        self.last_thinking_tokens = (
            None if details is None else getattr(details, "thinking_tokens", None)
        )

        return (
            text,
            response.usage.input_tokens,
            response.usage.output_tokens,
            response.model,
        )
