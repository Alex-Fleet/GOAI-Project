"""向量检索：VectorStore 契约 + 暴力实现（ARD §5 知识入库 / 决策：接口 + 暴力）。

接口对齐 Milvus（create_collection / insert / search / drop_collection）——二楼换真
Milvus 时只替换实现、契约不变。暴力实现 O(N) 余弦相似度，万级 chunk 毫秒级，
够一楼独立跑与演示；「假装用 Milvus 实际上暴力」指的就是这条路径。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class VectorHit:
    """一条检索命中（向量检索返回单位）。"""

    id: str
    score: float  # 余弦相似度 [-1, 1]
    payload: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class VectorStore(Protocol):
    """向量库契约（对齐 Milvus 主操作，够换实现）。"""

    def create_collection(self, name: str, dim: int) -> None: ...
    def insert(
        self,
        name: str,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]] | None = None,
    ) -> None: ...
    def search(self, name: str, query: list[float], top_k: int = 10) -> list[VectorHit]: ...
    def drop_collection(self, name: str) -> None: ...


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return list(vec)
    return [x / norm for x in vec]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class BruteForceVectorStore:
    """内存归一化向量 + 点积排序（归一化后点积 = 余弦相似度）。可 JSON 落盘。

    持久化：每次变更写 `persist_path` 文件（万级规模 JSON 完全够用）。
    数据不完整兜底：集合不存在时 search 返回空列表，不崩溃（对齐知识层「知识不完整不崩溃」）。
    """

    def __init__(self, persist_path: str | None = None):
        self._collections: dict[str, dict[str, Any]] = {}
        self._path = Path(persist_path) if persist_path else None
        if self._path is not None and self._path.exists():
            self._collections = json.loads(self._path.read_text(encoding="utf-8"))

    # ---- 契约实现 ----

    def create_collection(self, name: str, dim: int) -> None:
        if name in self._collections:
            return  # 幂等
        self._collections[name] = {"dim": dim, "ids": [], "vectors": [], "payloads": []}
        self._persist()

    def insert(
        self,
        name: str,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]] | None = None,
    ) -> None:
        col = self._require(name)
        payloads = payloads or [{} for _ in ids]
        if not (len(ids) == len(vectors) == len(payloads)):
            raise ValueError("ids/vectors/payloads 长度不一致")
        for i, vec in enumerate(vectors):
            if len(vec) != col["dim"]:
                raise ValueError(f"向量维度 {len(vec)} != 集合维度 {col['dim']}")
            nvec = _normalize(vec)
            if ids[i] in col["ids"]:  # 幂等：同 id 替换（重复 commit 安全）
                idx = col["ids"].index(ids[i])
                col["vectors"][idx] = nvec
                col["payloads"][idx] = payloads[i]
            else:
                col["ids"].append(ids[i])
                col["vectors"].append(nvec)
                col["payloads"].append(payloads[i])
        self._persist()

    def search(self, name: str, query: list[float], top_k: int = 10) -> list[VectorHit]:
        col = self._collections.get(name)
        if col is None:
            return []  # 集合不存在 → 空结果，不崩溃
        if len(query) != col["dim"]:
            raise ValueError(f"查询维度 {len(query)} != 集合维度 {col['dim']}")
        if not col["ids"]:
            return []  # 空集合 → 空结果
        q = _normalize(query)
        scored = [
            (col["ids"][i], _dot(q, col["vectors"][i]), col["payloads"][i])
            for i in range(len(col["ids"]))
        ]
        scored.sort(key=lambda t: t[1], reverse=True)
        return [VectorHit(i, s, p) for i, s, p in scored[:top_k]]

    def drop_collection(self, name: str) -> None:
        self._collections.pop(name, None)
        self._persist()

    # ---- 内部 ----

    def _require(self, name: str) -> dict[str, Any]:
        if name not in self._collections:
            raise KeyError(f"集合不存在: {name}（先 create_collection）")
        return self._collections[name]

    def _persist(self) -> None:
        if self._path is not None:
            self._path.write_text(json.dumps(self._collections), encoding="utf-8")
