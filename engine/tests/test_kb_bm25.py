"""D6 关键词检索测试：BM25Index（Jieba 分词 / 排序 / 边界 / 重复索引防护）。"""

from __future__ import annotations

from engine import BM25Index


def whitespace_tokenize(text: str) -> list[str]:
    return [t for t in text.split() if t]


def test_relevance_ranking():
    idx = BM25Index(tokenizer=whitespace_tokenize)
    idx.index("d1", ["piston", "rod", "wear"])
    idx.index("d2", ["spindle", "bearing", "wear"])
    idx.index("d3", ["coolant", "pump"])
    hits = idx.search("spindle bearing", top_k=3)
    assert hits[0].doc_id == "d2"  # 两个词都命中 → 分最高
    assert all(h.score > 0 for h in hits)


def test_chinese_jieba():
    import jieba

    idx = BM25Index(tokenizer=jieba.lcut)
    idx.index("c1", jieba.lcut("主轴轴承磨损导致振动超标"))
    idx.index("c2", jieba.lcut("冷却泵流量不足"))
    hits = idx.search("主轴轴承", top_k=2)
    assert hits[0].doc_id == "c1"


def test_empty_index_returns_empty():
    idx = BM25Index(tokenizer=whitespace_tokenize)
    assert idx.search("anything") == []


def test_empty_query_returns_empty():
    idx = BM25Index(tokenizer=whitespace_tokenize)
    idx.index("d1", ["a", "b"])
    assert idx.search("") == []
    assert idx.search("   ") == []


def test_duplicate_doc_rejected():
    idx = BM25Index(tokenizer=whitespace_tokenize)
    idx.index("d1", ["a"])
    try:
        idx.index("d1", ["b"])
    except ValueError:
        pass
    else:
        raise AssertionError("重复 index 同一 doc_id 应抛 ValueError")


def test_payload_attached():
    idx = BM25Index(tokenizer=whitespace_tokenize)
    idx.index("d1", ["rod"], {"doc_id": "doc", "source_ref": "doc#L1"})
    hits = idx.search("rod")
    assert hits[0].payload == {"doc_id": "doc", "source_ref": "doc#L1"}


def test_top_k_limits():
    idx = BM25Index(tokenizer=whitespace_tokenize)
    for i in range(5):
        idx.index(f"d{i}", [f"tok{i}"])
    hits = idx.search("tok0 tok1", top_k=1)
    assert len(hits) == 1
