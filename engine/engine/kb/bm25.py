"""关键词检索：Jieba 分词 + BM25 倒排（ARD §5 知识入库 / 决策：Jieba + BM25）。

确定性、可审计——本体推理的检索起点之一（关键词路径）。查询分词后按 BM25
打分排序，返回 chunk 命中。与向量检索互补：关键词精确 / 语义泛化，两条路都进推理核兜底。
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class BM25Hit:
    """一条关键词检索命中。"""

    doc_id: str
    score: float
    payload: dict = field(default_factory=dict)


class BM25Index:
    """倒排索引 + BM25 打分（k1/b 为 BM25 标准超参）。

    覆盖边界：重复 index 同一 doc_id 视为数据错误（抛 ValueError，防索引脏）；\
    空索引/空查询 → 空结果不崩溃。tokenizer 注入（默认为 jieba.lcut，测试可替换）。
    """

    def __init__(
        self, tokenizer: Callable[[str], list[str]] | None = None, k1: float = 1.5, b: float = 0.75
    ):
        if tokenizer is None:
            import jieba

            tokenizer = jieba.lcut
        self._tokenize = tokenizer
        self._k1, self._b = k1, b
        self._docs: dict[str, Counter] = {}  # doc_id -> term 频次
        self._df: Counter = Counter()  # term -> 出现文档数
        self._dl: dict[str, int] = {}  # doc_id -> 词数
        self._payloads: dict[str, dict] = {}
        self._avgdl = 0.0

    def index(self, doc_id: str, tokens: list[str], payload: dict | None = None) -> None:
        if doc_id in self._docs:
            raise ValueError(f"doc_id 已存在，禁止覆盖: {doc_id}")
        counter = Counter(tokens)
        self._docs[doc_id] = counter
        self._dl[doc_id] = len(tokens)
        self._payloads[doc_id] = payload or {}
        for term in counter:
            self._df[term] += 1
        n = len(self._docs)
        self._avgdl = sum(self._dl.values()) / n if n else 0.0

    def search(self, query: str, top_k: int = 10) -> list[BM25Hit]:
        if not self._docs:
            return []
        terms = self._tokenize(query)
        if not terms:
            return []
        n = len(self._docs)
        scores: Counter = Counter()
        for term in set(terms):  # 查询内去重，防长文本自我放大
            df = self._df.get(term, 0)
            if df == 0:
                continue
            idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)  # 平滑，防除零
            for doc_id, counter in self._docs.items():
                tf = counter.get(term, 0)
                if tf == 0:
                    continue
                dl = self._dl[doc_id]
                denom = tf + self._k1 * (1 - self._b + self._b * dl / self._avgdl)
                scores[doc_id] += idf * tf * (self._k1 + 1) / denom
        return [
            BM25Hit(doc_id, score, self._payloads[doc_id])
            for doc_id, score in scores.most_common(top_k)
        ]

    def contains(self, doc_id: str) -> bool:
        return doc_id in self._docs

    def __len__(self) -> int:
        return len(self._docs)
