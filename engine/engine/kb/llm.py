"""LLM 客户端（D6 抽取 / 切块兜底）：DeepSeek API（OpenAI 兼容）。

密钥只从环境变量读取（安全红线：密钥不进代码/配置文件）；未配置时抛 ValueError，
不伪造网络。一楼离线测试用 stub LLM（依赖注入），真实客户端不参与测试网络路径。
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

import httpx


@runtime_checkable
class LLMProtocol(Protocol):
    """D6 用到的 LLM 最小能力：单轮 chat。"""

    def chat(self, system: str, user: str, json_mode: bool = False) -> str: ...


class DeepSeekClient:
    """DeepSeek chat 客户端。`json_mode=True` 时要求输出合法 JSON 对象。"""

    BASE_URL = "https://api.deepseek.com/v1/chat/completions"
    MODEL = "deepseek-chat"

    def __init__(self, api_key: str | None = None, timeout: float = 60.0):
        key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise ValueError("缺少 DEEPSEEK_API_KEY 环境变量（D6 接真实 LLM 时设置）")
        self._key = key
        self._timeout = timeout

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        payload: dict = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,  # 抽取任务要确定性，不放飞
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        resp = httpx.post(
            self.BASE_URL,
            headers={"Authorization": f"Bearer {self._key}"},
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
