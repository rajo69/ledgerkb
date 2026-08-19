"""Provider adapters, against a mocked endpoint. No network, no credentials."""

from __future__ import annotations

import httpx
import pytest
import respx
from pydantic import BaseModel

from ledgerkb.core.config import Config
from ledgerkb.core.errors import ConfigError, ProviderError
from ledgerkb.core.ports import ChatModel, Embedder
from ledgerkb.providers.factory import build_chat, build_embedder
from ledgerkb.providers.local import KNOWN_DIMENSIONS, LocalEmbedder
from ledgerkb.providers.openai_compat import (
    _CAPABILITIES,
    OpenAICompatChat,
    OpenAICompatEmbedder,
)

BASE = "https://api.example.invalid/v1"


class Verdict(BaseModel):
    grade: str
    confidence: float


@pytest.fixture(autouse=True)
def _clean_capability_cache():
    _CAPABILITIES.clear()
    yield
    _CAPABILITIES.clear()


def chat(**kw) -> OpenAICompatChat:
    return OpenAICompatChat("some/model", BASE, requires_key=False, **kw)


def reply(content: str) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


class TestChat:
    @respx.mock
    def test_it_completes(self) -> None:
        respx.post(f"{BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json=reply("Attercliffe."))
        )
        assert chat().complete([{"role": "user", "content": "where?"}]) == "Attercliffe."

    @respx.mock
    def test_it_records_token_usage(self) -> None:
        """Cost accounting and the budget guard both need this."""
        respx.post(f"{BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json=reply("ok"))
        )
        model = chat()
        model.complete([{"role": "user", "content": "hi"}])
        assert model.usage == [{"input_tokens": 11, "output_tokens": 7}]

    @respx.mock
    def test_no_tools_are_sent_unless_a_caller_asks(self) -> None:
        """The anti-injection control is architectural, so it is asserted here.

        Untrusted document text must never reach a context that can act. A
        default that quietly attached tools would undo that with no visible
        change at any call site.
        """
        route = respx.post(f"{BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json=reply("ok"))
        )
        chat().complete([{"role": "user", "content": "summarise this document"}])
        assert "tools" not in route.calls[0].request.content.decode()

    @respx.mock
    def test_it_retries_a_rate_limit_then_succeeds(self) -> None:
        respx.post(f"{BASE}/chat/completions").mock(
            side_effect=[
                httpx.Response(429, text="slow down"),
                httpx.Response(200, json=reply("second time lucky")),
            ]
        )
        assert chat().complete([{"role": "user", "content": "x"}]) == "second time lucky"

    @respx.mock
    def test_a_client_error_is_not_retried_and_names_the_endpoint(self) -> None:
        route = respx.post(f"{BASE}/chat/completions").mock(
            return_value=httpx.Response(401, text="bad key")
        )
        with pytest.raises(ProviderError, match="401"):
            chat().complete([{"role": "user", "content": "x"}])
        assert route.call_count == 1, "a 401 will not fix itself on retry"

    def test_a_missing_key_names_the_variable_and_the_alternative(self) -> None:
        with pytest.raises(ProviderError, match="NOT_SET_ANYWHERE"):
            OpenAICompatChat("m", BASE, api_key_env="NOT_SET_ANYWHERE")


class TestStructuredOutput:
    @respx.mock
    def test_it_uses_a_strict_schema_when_the_endpoint_supports_one(self) -> None:
        route = respx.post(f"{BASE}/chat/completions").mock(
            return_value=httpx.Response(
                200, json=reply('{"grade":"correct","confidence":0.9}')
            )
        )
        out = chat().structured([{"role": "user", "content": "grade it"}], Verdict)
        assert out.grade == "correct"
        assert "json_schema" in route.calls[-1].request.content.decode()

    @respx.mock
    def test_it_degrades_when_the_endpoint_rejects_strict_schemas(self) -> None:
        """Routed models on aggregators often cannot do strict schemas.

        The alternative to degrading is crashing on a provider that is
        otherwise perfectly usable.
        """
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            body = request.content.decode()
            if "json_schema" in body:
                return httpx.Response(400, text="response_format not supported")
            return httpx.Response(200, json=reply('{"grade":"ambiguous","confidence":0.4}'))

        respx.post(f"{BASE}/chat/completions").mock(side_effect=handler)
        out = chat().structured([{"role": "user", "content": "grade it"}], Verdict)
        assert out.grade == "ambiguous"

    @respx.mock
    def test_it_finds_json_wrapped_in_prose(self) -> None:
        payload = '{"grade":"incorrect","confidence":0.1}'
        fenced = f'Here you go:\n```json\n{payload}\n```\nHope that helps.'
        respx.post(f"{BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json=reply(fenced))
        )
        assert chat().structured([{"role": "user", "content": "x"}], Verdict).grade == "incorrect"

    @respx.mock
    def test_it_gives_up_loudly_rather_than_returning_nonsense(self) -> None:
        respx.post(f"{BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json=reply("I would rather not."))
        )
        with pytest.raises(ProviderError, match="Verdict"):
            chat().structured([{"role": "user", "content": "x"}], Verdict)

    @respx.mock
    def test_capabilities_are_probed_once_per_endpoint_and_model(self) -> None:
        route = respx.post(f"{BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json=reply('{"ok":true}'))
        )
        model = chat()
        model.capabilities()
        model.capabilities()
        assert route.call_count == 1


class TestEmbedder:
    @respx.mock
    def test_it_batches_and_preserves_order(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            import json

            inputs = json.loads(request.content)["input"]
            # Returned out of order on purpose: the adapter must sort by index.
            data = [
                {"index": i, "embedding": [float(i)] * 4}
                for i in reversed(range(len(inputs)))
            ]
            return httpx.Response(200, json={"data": data})

        respx.post(f"{BASE}/embeddings").mock(side_effect=handler)
        out = OpenAICompatEmbedder(
            "m", BASE, dimensions=4, batch_size=2, requires_key=False
        ).embed(["a", "b", "c"])
        assert [v[0] for v in out] == [0.0, 1.0, 0.0]

    @respx.mock
    def test_a_wrong_width_is_refused_before_anything_is_stored(self) -> None:
        respx.post(f"{BASE}/embeddings").mock(
            return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0] * 8}]})
        )
        embedder = OpenAICompatEmbedder("m", BASE, dimensions=1024, requires_key=False)
        with pytest.raises(ProviderError, match="locked"):
            embedder.embed(["a"])


class TestLocalEmbedder:
    def test_a_model_dimension_mismatch_is_caught_at_construction(self) -> None:
        """Before a corpus is embedded, not after."""
        with pytest.raises(ProviderError, match="locked after the first index build"):
            LocalEmbedder("BAAI/bge-small-en-v1.5", dimensions=1024)

    def test_the_default_is_a_thousand_and_twenty_four_dimensions(self) -> None:
        assert KNOWN_DIMENSIONS[LocalEmbedder().name] == 1024

    def test_no_non_commercial_model_is_offered(self) -> None:
        """jina-embeddings-v3 is 1024 dims and otherwise a fine choice, but
        CC-BY-NC-4.0 is non-commercial and this project does not ship one."""
        assert not any("jina" in name for name in KNOWN_DIMENSIONS)


class TestFactory:
    def test_the_default_config_builds_a_local_embedder(self) -> None:
        embedder = build_embedder(Config())
        assert isinstance(embedder, Embedder)
        assert isinstance(embedder, LocalEmbedder)

    def test_an_unknown_provider_says_what_is_known(self) -> None:
        cfg = Config()
        cfg.embeddings.provider = "telepathy"
        with pytest.raises(ConfigError, match="Embedder port"):
            build_embedder(cfg)

    def test_local_is_matched_on_the_hostname_not_a_substring(self) -> None:
        """A substring test reads https://localhost.example.com as local."""
        from ledgerkb.providers.factory import _needs_key

        assert _needs_key("http://localhost:11434/v1") is False
        assert _needs_key("http://127.0.0.1:8000/v1") is False
        assert _needs_key("https://localhost.example.com/v1") is True
        assert _needs_key("https://evil-localhost.com/v1") is True
        assert _needs_key("https://openrouter.ai/api/v1") is True

    def test_a_local_endpoint_needs_no_key(self) -> None:
        cfg = Config()
        cfg.chat.base_url = "http://localhost:11434/v1"
        cfg.chat.api_key_env = "DEFINITELY_NOT_SET"
        model = build_chat(cfg)
        assert isinstance(model, ChatModel)

    def test_the_cheap_tier_selects_the_cheap_model(self) -> None:
        cfg = Config()
        cfg.chat.base_url = "http://localhost:11434/v1"
        assert build_chat(cfg, cheap=True).name == cfg.chat.cheap.model
        assert build_chat(cfg).name == cfg.chat.model
