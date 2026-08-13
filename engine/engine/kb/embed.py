"""Embedding 客户端（D6 向量化）：硅基流动 bge-m3（云端，中文，1024 维）。

密钥只从环境变量读取（SILICONFLOW_API_KEY）；未配置时抛 ValueError。
`embed` 按输入顺序返回向量（对齐 OpenAI 兼容接口，按 index 排序保证顺序）。
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

import httpx


@runtime_checkable
class EmbedderProtocol(Protocol):
    """D6 用到的 embedding 最小能力。"""

    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def dim(self) -> int: ...


class SiliconFlowEmbedder:
    """硅基流动 bge-m3（BAAI/bge-m3），dense 向量 1024 维。"""

    BASE_URL = "https://api.siliconflow.cn/v1/embeddings"
    MODEL = "BAAI/bge-m3"
    DIM = 1024

    def __init__(self, api_key: str | None = None, timeout: float = 60.0):
        key = api_key or os.environ.get("SILICONFLOW_API_KEY")
        if not key:
            raise ValueError(
                "缺少 SILICONFLOW_API_KEY 环境变量（D6 向量化接真实 embedding 时设置）"
            )
        self._key = key
        self._timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = httpx.post(
            self.BASE_URL,
            headers={"Authorization": f"Bearer {self._key}"},
            json={"model": self.MODEL, "input": texts},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        items = sorted(data["data"], key=lambda x: x["index"])  # 保序，防服务端乱序
        return [it["embedding"] for it in items]

    def dim(self) -> int:
        return self.DIM
