from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from docpilot.exceptions import MappingError
from docpilot.mapping.base import BaseLLMMapper, MappingResult, TemplateSection
from docpilot.mapping import benchmark
from tests.mocks.llm_mock import MockMapper

SECTIONS = [TemplateSection("서론"), TemplateSection("결론")]
CONTENT = "2025년 사업 계획 내용입니다."


class TestMockMapper:
    def test_returns_mapping_result(self):
        mapper = MockMapper()
        result = mapper.map(CONTENT, SECTIONS)
        assert isinstance(result, MappingResult)
        assert set(result.sections.keys()) == {"서론", "결론"}

    def test_records_calls(self):
        mapper = MockMapper()
        mapper.map(CONTENT, SECTIONS)
        assert len(mapper.calls) == 1
        assert mapper.calls[0][0] == CONTENT

    def test_total_tokens(self):
        mapper = MockMapper()
        result = mapper.map(CONTENT, SECTIONS)
        assert result.total_tokens == result.input_tokens + result.output_tokens


class TestParseResponse:
    """Test BaseLLMMapper._parse_response via MockMapper subclass."""

    def _mapper(self):
        return MockMapper()

    def test_valid_json(self):
        mapper = self._mapper()
        raw = json.dumps({"sections": {"서론": "내용A", "결론": "내용B"}})
        result = mapper._parse_response(raw, SECTIONS)
        assert result["서론"] == "내용A"

    def test_json_with_prefix_text(self):
        mapper = self._mapper()
        raw = '다음은 결과입니다.\n' + json.dumps({"sections": {"서론": "A", "결론": "B"}})
        result = mapper._parse_response(raw, SECTIONS)
        assert result["결론"] == "B"

    def test_missing_section_raises(self):
        mapper = self._mapper()
        raw = json.dumps({"sections": {"서론": "A"}})
        with pytest.raises(MappingError, match="missing sections"):
            mapper._parse_response(raw, SECTIONS)

    def test_invalid_json_raises(self):
        mapper = self._mapper()
        with pytest.raises(MappingError, match="Failed to parse"):
            mapper._parse_response("not json at all", SECTIONS)

    def test_invalid_json_without_truncation_flag_gives_generic_error(self):
        """Malformed-but-not-truncated JSON must NOT be blamed on max_tokens."""
        mapper = self._mapper()
        with pytest.raises(MappingError, match="Failed to parse") as exc_info:
            mapper._parse_response("not json at all", SECTIONS, truncated=False)
        assert "max_tokens" not in str(exc_info.value)

    def test_truncated_broken_json_blames_max_tokens(self):
        mapper = self._mapper()
        raw = '{"sections": {"서론": "내용이 중간에 끊'  # cut off mid-string, no closing brace
        with pytest.raises(MappingError, match="max_tokens") as exc_info:
            mapper._parse_response(raw, SECTIONS, truncated=True)
        assert "잘려" in str(exc_info.value)

    def test_truncated_missing_section_blames_max_tokens(self):
        """JSON that parses fine but is missing a section because generation was cut off."""
        mapper = self._mapper()
        raw = json.dumps({"sections": {"서론": "A"}})
        with pytest.raises(MappingError, match="max_tokens") as exc_info:
            mapper._parse_response(raw, SECTIONS, truncated=True)
        assert "결론" in str(exc_info.value)


class TestClaudeMapper:
    def test_map_calls_api(self):
        from docpilot.mapping.claude import ClaudeMapper

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(
            {"sections": {"서론": "내용A", "결론": "내용B"}}
        ))]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_response
            mapper = ClaudeMapper(api_key="test-key")
            result = mapper.map(CONTENT, SECTIONS)

        assert result.sections["서론"] == "내용A"
        assert result.model.startswith("claude")

    def test_missing_api_key_raises(self):
        from docpilot.mapping.claude import ClaudeMapper
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(MappingError, match="API key"):
                ClaudeMapper(api_key=None)

    def test_map_truncated_by_max_tokens_blames_max_tokens(self):
        """stop_reason=max_tokens + broken JSON → error must name max_tokens as the cause."""
        from docpilot.mapping.claude import ClaudeMapper

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"sections": {"서론": "내용이 중간에 끊')]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_response.stop_reason = "max_tokens"

        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_response
            mapper = ClaudeMapper(api_key="test-key")
            with pytest.raises(MappingError, match="max_tokens"):
                mapper.map(CONTENT, SECTIONS)

    def test_map_broken_json_without_truncation_is_generic_error(self):
        """Same broken JSON, but stop_reason=end_turn → must NOT blame max_tokens."""
        from docpilot.mapping.claude import ClaudeMapper

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"sections": {"서론": "내용이 중간에 끊')]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_response.stop_reason = "end_turn"

        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_response
            mapper = ClaudeMapper(api_key="test-key")
            with pytest.raises(MappingError) as exc_info:
                mapper.map(CONTENT, SECTIONS)
        assert "max_tokens" not in str(exc_info.value)

    def test_map_accepts_instructions_positionally(self):
        """RagMapper/generate_from_content call mapper.map(content, sections, instructions) —
        must not raise TypeError, and the instructions text must reach the prompt."""
        from docpilot.mapping.claude import ClaudeMapper

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(
            {"sections": {"서론": "A", "결론": "B"}}
        ))]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5

        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_response
            mapper = ClaudeMapper(api_key="test-key")
            mapper.map(CONTENT, SECTIONS, "전문 용어는 한국어로 병기하세요")

            sent_prompt = MockClient.return_value.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "전문 용어는 한국어로 병기하세요" in sent_prompt


class TestBenchmark:
    def test_run_returns_results(self):
        mappers = {"a": MockMapper("model-a"), "b": MockMapper("model-b")}
        results = benchmark.run(CONTENT, SECTIONS, mappers)
        assert len(results) == 2
        assert {r.model for r in results} == {"a", "b"}

    def test_report_contains_models(self):
        mappers = {"claude": MockMapper()}
        results = benchmark.run(CONTENT, SECTIONS, mappers)
        report = benchmark.report(results)
        assert "claude" in report
        assert "서론" in report

    def test_empty_report(self):
        assert benchmark.report([]) == "No results."

    def test_failed_mapper_does_not_abort(self):
        class FailingMapper(MockMapper):
            def map(self, content, sections):
                raise MappingError("API key missing")

        mappers = {"good": MockMapper(), "bad": FailingMapper()}
        results = benchmark.run(CONTENT, SECTIONS, mappers)
        assert len(results) == 2
        good = next(r for r in results if r.model == "good")
        bad = next(r for r in results if r.model == "bad")
        assert good.error is None
        assert bad.error is not None
        assert bad.sections == {}

    def test_report_shows_error_status(self):
        class FailingMapper(MockMapper):
            def map(self, content, sections):
                raise MappingError("invalid key")

        mappers = {"ok": MockMapper(), "fail": FailingMapper()}
        results = benchmark.run(CONTENT, SECTIONS, mappers)
        report = benchmark.report(results)
        assert "오류" in report
        assert "OK" in report

    def test_report_all_failed(self):
        class FailingMapper(MockMapper):
            def map(self, content, sections):
                raise MappingError("no key")

        mappers = {"a": FailingMapper(), "b": FailingMapper()}
        results = benchmark.run(CONTENT, SECTIONS, mappers)
        report = benchmark.report(results)
        assert "모든 LLM 호출이 실패했습니다" in report


class TestGeminiMapper:
    def test_map_calls_api(self):
        import sys
        from docpilot.mapping.gemini import GeminiMapper

        mock_usage = MagicMock()
        mock_usage.prompt_token_count = 80
        mock_usage.candidates_token_count = 40

        mock_response = MagicMock()
        mock_response.text = json.dumps({"sections": {"서론": "내용A", "결론": "내용B"}})
        mock_response.usage_metadata = mock_usage

        mock_genai = MagicMock()
        mock_genai.Client.return_value.models.generate_content.return_value = mock_response

        with patch.dict(sys.modules, {"google.genai": mock_genai}):
            mapper = GeminiMapper(api_key="test-key")
            result = mapper.map(CONTENT, SECTIONS)

        assert result.sections["서론"] == "내용A"
        assert result.input_tokens == 80

    def test_map_truncated_by_max_tokens_blames_max_tokens(self):
        """candidate.finish_reason=MAX_TOKENS + broken JSON → error must name max_tokens."""
        import sys
        from docpilot.mapping.gemini import GeminiMapper

        mock_usage = MagicMock()
        mock_usage.prompt_token_count = 80
        mock_usage.candidates_token_count = 40

        mock_candidate = MagicMock()
        mock_candidate.finish_reason = "MAX_TOKENS"

        mock_response = MagicMock()
        mock_response.text = '{"sections": {"서론": "내용이 중간에 끊'
        mock_response.usage_metadata = mock_usage
        mock_response.candidates = [mock_candidate]

        mock_genai = MagicMock()
        mock_genai.Client.return_value.models.generate_content.return_value = mock_response

        with patch.dict(sys.modules, {"google.genai": mock_genai}):
            mapper = GeminiMapper(api_key="test-key")
            with pytest.raises(MappingError, match="max_tokens"):
                mapper.map(CONTENT, SECTIONS)

    def test_missing_api_key_raises(self):
        from docpilot.mapping.gemini import GeminiMapper
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(MappingError, match="API key"):
                GeminiMapper(api_key=None)

    def test_map_accepts_instructions_positionally(self):
        """RagMapper/generate_from_content call mapper.map(content, sections, instructions) —
        must not raise TypeError, and the instructions text must reach the prompt."""
        import sys
        from docpilot.mapping.gemini import GeminiMapper

        mock_usage = MagicMock()
        mock_usage.prompt_token_count = 10
        mock_usage.candidates_token_count = 5

        mock_response = MagicMock()
        mock_response.text = json.dumps({"sections": {"서론": "A", "결론": "B"}})
        mock_response.usage_metadata = mock_usage

        mock_genai = MagicMock()
        mock_genai.Client.return_value.models.generate_content.return_value = mock_response

        with patch.dict(sys.modules, {"google.genai": mock_genai}):
            mapper = GeminiMapper(api_key="test-key")
            mapper.map(CONTENT, SECTIONS, "전문 용어는 한국어로 병기하세요")

            sent_prompt = mock_genai.Client.return_value.models.generate_content.call_args.kwargs["contents"]
        assert "전문 용어는 한국어로 병기하세요" in sent_prompt


class TestOpenAICompatMapper:
    def test_grok_mapper(self):
        from docpilot.mapping.openai_compat import GrokMapper, OpenAICompatMapper

        with patch.dict("os.environ", {"XAI_API_KEY": "xai-test"}):
            mapper = GrokMapper()

        assert isinstance(mapper, OpenAICompatMapper)
        assert "x.ai" in mapper._base_url

    def test_ollama_mapper_defaults(self):
        from docpilot.mapping.openai_compat import OllamaMapper

        mapper = OllamaMapper()
        assert "localhost" in mapper._base_url
        assert mapper._model == "llama3.2"

    def test_ollama_custom_model(self):
        from docpilot.mapping.openai_compat import OllamaMapper

        mapper = OllamaMapper(model="mistral")
        assert mapper._model == "mistral"

    def test_grok_missing_key_raises(self):
        from docpilot.mapping.openai_compat import GrokMapper
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(MappingError, match="API key"):
                GrokMapper(api_key=None)

    def test_map_calls_api(self):
        from docpilot.mapping.openai_compat import OllamaMapper

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps(
            {"sections": {"서론": "내용A", "결론": "내용B"}}
        )
        mock_response.usage.prompt_tokens = 60
        mock_response.usage.completion_tokens = 30

        with patch("openai.OpenAI") as MockClient:
            MockClient.return_value.chat.completions.create.return_value = mock_response
            mapper = OllamaMapper(model="llama3.2")
            result = mapper.map(CONTENT, SECTIONS)

        assert result.sections["결론"] == "내용B"

    def test_map_accepts_instructions_positionally(self):
        """RagMapper/generate_from_content call mapper.map(content, sections, instructions) —
        must not raise TypeError, and the instructions text must reach the prompt."""
        from docpilot.mapping.openai_compat import OllamaMapper

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps(
            {"sections": {"서론": "A", "결론": "B"}}
        )
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        with patch("openai.OpenAI") as MockClient:
            MockClient.return_value.chat.completions.create.return_value = mock_response
            mapper = OllamaMapper(model="llama3.2")
            mapper.map(CONTENT, SECTIONS, "전문 용어는 한국어로 병기하세요")

            sent_prompt = MockClient.return_value.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "전문 용어는 한국어로 병기하세요" in sent_prompt


class TestOpenAIMapper:
    def test_map_calls_api(self):
        from docpilot.mapping.openai import OpenAIMapper

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps(
            {"sections": {"서론": "내용A", "결론": "내용B"}}
        )
        mock_response.usage.prompt_tokens = 60
        mock_response.usage.completion_tokens = 30

        with patch("openai.OpenAI") as MockClient:
            MockClient.return_value.chat.completions.create.return_value = mock_response
            mapper = OpenAIMapper(api_key="test-key")
            result = mapper.map(CONTENT, SECTIONS)

        assert result.sections["결론"] == "내용B"
        assert result.model.startswith("gpt")

    def test_map_truncated_by_max_tokens_blames_max_tokens(self):
        """finish_reason=length + broken JSON → error must name max_tokens as the cause."""
        from docpilot.mapping.openai import OpenAIMapper

        mock_response = MagicMock()
        mock_response.choices[0].message.content = '{"sections": {"서론": "내용이 중간에 끊'
        mock_response.choices[0].finish_reason = "length"
        mock_response.usage.prompt_tokens = 60
        mock_response.usage.completion_tokens = 30

        with patch("openai.OpenAI") as MockClient:
            MockClient.return_value.chat.completions.create.return_value = mock_response
            mapper = OpenAIMapper(api_key="test-key")
            with pytest.raises(MappingError, match="max_tokens"):
                mapper.map(CONTENT, SECTIONS)

    def test_complete_calls_api(self):
        from docpilot.mapping.openai import OpenAIMapper

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "1"

        with patch("openai.OpenAI") as MockClient:
            MockClient.return_value.chat.completions.create.return_value = mock_response
            mapper = OpenAIMapper(api_key="test-key")
            result = mapper.complete("프롬프트")

        assert result == "1"

    def test_missing_api_key_raises(self):
        from docpilot.mapping.openai import OpenAIMapper
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(MappingError, match="API key"):
                OpenAIMapper(api_key=None)

    def test_map_accepts_instructions_positionally(self):
        """RagMapper/generate_from_content call mapper.map(content, sections, instructions) —
        must not raise TypeError, and the instructions text must reach the prompt."""
        from docpilot.mapping.openai import OpenAIMapper

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps(
            {"sections": {"서론": "A", "결론": "B"}}
        )
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        with patch("openai.OpenAI") as MockClient:
            MockClient.return_value.chat.completions.create.return_value = mock_response
            mapper = OpenAIMapper(api_key="test-key")
            mapper.map(CONTENT, SECTIONS, "전문 용어는 한국어로 병기하세요")

            sent_prompt = MockClient.return_value.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "전문 용어는 한국어로 병기하세요" in sent_prompt
