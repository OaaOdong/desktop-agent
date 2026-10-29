"""OpenAI 兼容的 LLM 客户端（纯标准库 urllib 实现，不依赖 openai SDK）。

任何提供 /v1/chat/completions 且支持 tools/tool_calls 的服务商都能用：
OpenAI、DeepSeek、通义千问、本地 Ollama 等。
"""
import json
import urllib.request
import urllib.error


class LLMError(RuntimeError):
    pass


class OpenAICompatibleLLM:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 60):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, messages: list, tools: list | None = None, temperature: float = 0.2) -> dict:
        """一次非流式调用，返回标准化结果：
        {"content": str|None, "tool_calls": [{"name":..,"arguments":{..}}, ...]}
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise LLMError(f"HTTP {e.code}: {detail[:500]}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"网络错误：{e.reason}") from e

        if "error" in data:
            raise LLMError(f"API 错误：{data['error']}")

        msg = data["choices"][0]["message"]
        content = msg.get("content")

        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments", "") or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"name": fn.get("name", ""), "arguments": args})

        return {"content": content, "tool_calls": tool_calls}
