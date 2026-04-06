from unittest.mock import MagicMock, patch

from beaconhill.client import OllamaClient, _classify_error
from beaconhill.models import Message, Role, ToolCall


class TestClassifyError:
    def test_connection_refused(self):
        assert _classify_error(Exception("Connection refused")) == "connection"

    def test_connect_error(self):
        assert _classify_error(Exception("could not connect")) == "connection"

    def test_model_not_found(self):
        assert _classify_error(Exception("model not found")) == "model_not_found"

    def test_pull_error(self):
        assert _classify_error(Exception("try to pull the model")) == "model_not_found"

    def test_timeout(self):
        assert _classify_error(Exception("request timed out")) == "timeout"

    def test_unknown(self):
        assert _classify_error(Exception("something weird")) == "unknown"


class TestParseResponse:
    def _make_client(self):
        with patch("beaconhill.client.ollama_lib"):
            return OllamaClient()

    def test_text_response(self):
        client = self._make_client()
        response = {
            "message": {"role": "assistant", "content": "Hello!"},
            "prompt_eval_count": 100,
            "eval_count": 20,
        }
        msg = client._parse_response(response)
        assert msg.role == Role.ASSISTANT
        assert msg.content == "Hello!"
        assert msg.tool_calls is None
        assert client.last_prompt_tokens == 100
        assert client.last_completion_tokens == 20
        assert client.last_total_tokens == 120

    def test_tool_call_response(self):
        client = self._make_client()
        response = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "read_file",
                            "arguments": {"file_path": "test.py"},
                        }
                    }
                ],
            },
            "prompt_eval_count": 50,
            "eval_count": 10,
        }
        msg = client._parse_response(response)
        assert msg.role == Role.ASSISTANT
        assert msg.content is None  # empty string -> None
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "read_file"
        assert msg.tool_calls[0].arguments == {"file_path": "test.py"}

    def test_multiple_tool_calls(self):
        client = self._make_client()
        response = {
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"function": {"name": "glob", "arguments": {"pattern": "*.py"}}},
                    {"function": {"name": "bash", "arguments": {"command": "ls"}}},
                ],
            },
            "prompt_eval_count": 0,
            "eval_count": 0,
        }
        msg = client._parse_response(response)
        assert len(msg.tool_calls) == 2
        assert msg.tool_calls[0].name == "glob"
        assert msg.tool_calls[1].name == "bash"

    def test_missing_token_counts(self):
        client = self._make_client()
        response = {"message": {"role": "assistant", "content": "hi"}}
        client._parse_response(response)
        assert client.last_prompt_tokens == 0
        assert client.last_completion_tokens == 0


class TestChat:
    def test_chat_converts_messages(self):
        with patch("beaconhill.client.ollama_lib") as mock_lib:
            mock_client = MagicMock()
            mock_lib.Client.return_value = mock_client
            mock_client.chat.return_value = {
                "message": {"role": "assistant", "content": "response"},
                "prompt_eval_count": 10,
                "eval_count": 5,
            }

            client = OllamaClient(model="test-model")
            messages = [Message(role=Role.USER, content="hello")]
            result = client.chat(messages)

            mock_client.chat.assert_called_once()
            call_kwargs = mock_client.chat.call_args
            assert call_kwargs.kwargs["model"] == "test-model"
            assert call_kwargs.kwargs["messages"] == [{"role": "user", "content": "hello"}]
            assert result.content == "response"

    def test_chat_passes_tools(self):
        with patch("beaconhill.client.ollama_lib") as mock_lib:
            mock_client = MagicMock()
            mock_lib.Client.return_value = mock_client
            mock_client.chat.return_value = {
                "message": {"role": "assistant", "content": "ok"},
                "prompt_eval_count": 0,
                "eval_count": 0,
            }

            client = OllamaClient()
            tools = [{"type": "function", "function": {"name": "test"}}]
            client.chat([Message(role=Role.USER, content="hi")], tools=tools)

            call_kwargs = mock_client.chat.call_args.kwargs
            assert call_kwargs["tools"] == tools


class TestRetry:
    def test_model_not_found_no_retry(self):
        with patch("beaconhill.client.ollama_lib") as mock_lib:
            mock_client = MagicMock()
            mock_lib.Client.return_value = mock_client
            mock_client.chat.side_effect = Exception("model not found")

            client = OllamaClient()
            import pytest
            with pytest.raises(RuntimeError, match="not found"):
                client.chat([Message(role=Role.USER, content="hi")])
            assert mock_client.chat.call_count == 1

    @patch("beaconhill.client.time.sleep")
    def test_connection_retries(self, mock_sleep):
        with patch("beaconhill.client.ollama_lib") as mock_lib:
            mock_client = MagicMock()
            mock_lib.Client.return_value = mock_client
            mock_client.chat.side_effect = Exception("connection refused")

            client = OllamaClient()
            import pytest
            with pytest.raises(ConnectionError):
                client.chat([Message(role=Role.USER, content="hi")])
            assert mock_client.chat.call_count == 3
            assert mock_sleep.call_count == 2

    @patch("beaconhill.client.time.sleep")
    def test_connection_recovers(self, mock_sleep):
        with patch("beaconhill.client.ollama_lib") as mock_lib:
            mock_client = MagicMock()
            mock_lib.Client.return_value = mock_client
            mock_client.chat.side_effect = [
                Exception("connection refused"),
                {"message": {"role": "assistant", "content": "recovered"},
                 "prompt_eval_count": 0, "eval_count": 0},
            ]

            client = OllamaClient()
            result = client.chat([Message(role=Role.USER, content="hi")])
            assert result.content == "recovered"
            assert mock_client.chat.call_count == 2

    @patch("beaconhill.client.time.sleep")
    def test_retry_callback_receives_attempt_metadata(self, mock_sleep):
        with patch("beaconhill.client.ollama_lib") as mock_lib:
            mock_client = MagicMock()
            mock_lib.Client.return_value = mock_client
            mock_client.chat.side_effect = [
                Exception("connection refused"),
                {"message": {"role": "assistant", "content": "recovered"},
                 "prompt_eval_count": 0, "eval_count": 0},
            ]

            callback = MagicMock()
            client = OllamaClient()
            result = client.chat([Message(role=Role.USER, content="hi")], on_retry=callback)

            assert result.content == "recovered"
            callback.assert_called_once_with(1, 2, "connection")


class TestChatOrStream:
    def test_returns_message_with_tool_calls(self):
        with patch("beaconhill.client.ollama_lib") as mock_lib:
            mock_client = MagicMock()
            mock_lib.Client.return_value = mock_client
            mock_client.chat.return_value = {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"function": {"name": "bash", "arguments": {"command": "ls"}}}
                    ],
                },
                "prompt_eval_count": 0,
                "eval_count": 0,
            }

            client = OllamaClient()
            msg, stream = client.chat_or_stream([Message(role=Role.USER, content="hi")])
            assert msg is not None
            assert msg.tool_calls is not None
            assert stream is None

    def test_returns_true_stream_without_tool_calls(self):
        with patch("beaconhill.client.ollama_lib") as mock_lib:
            mock_client = MagicMock()
            mock_lib.Client.return_value = mock_client
            mock_client.chat.side_effect = [
                {
                    "message": {"role": "assistant", "content": "Hello!"},
                    "prompt_eval_count": 0,
                    "eval_count": 0,
                },
                iter([
                    {"message": {"content": "Hel"}},
                    {"message": {"content": "lo!"}},
                ]),
            ]

            client = OllamaClient()
            msg, stream = client.chat_or_stream([Message(role=Role.USER, content="hi")])
            assert msg is None
            assert stream is not None
            chunks = list(stream)
            assert chunks == ["Hel", "lo!"]
            assert mock_client.chat.call_count == 2

    def test_falls_back_to_non_streaming_text_on_stream_error(self):
        with patch("beaconhill.client.ollama_lib") as mock_lib:
            mock_client = MagicMock()
            mock_lib.Client.return_value = mock_client
            mock_client.chat.side_effect = [
                {
                    "message": {"role": "assistant", "content": "Hello!"},
                    "prompt_eval_count": 0,
                    "eval_count": 0,
                },
                Exception("stream failed"),
            ]

            client = OllamaClient()
            msg, stream = client.chat_or_stream([Message(role=Role.USER, content="hi")])
            assert msg is None
            assert stream is not None
            chunks = list(stream)
            assert chunks == ["Hello!"]
