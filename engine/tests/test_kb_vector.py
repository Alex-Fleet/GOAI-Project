"""D6 向量检索测试：BruteForceVectorStore 契约实现（正常/空/维度/持久化/幂等）。"""

from __future__ import annotations

from engine import BruteForceVectorStore


def test_insert_and_search_ranking(tmp_path):
    store = BruteForceVectorStore()
    store.create_collection("chunks", dim=4)
    store.insert(
        "chunks",
        ["a", "b", "c"],
        [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.5, 0.5, 0.0, 0.0]],
        [{"doc_id": "d1"}, {"doc_id": "d2"}, {"doc_id": "d3"}],
    )
    hits = store.search("chunks", [1.0, 0.0, 0.0, 0.0], top_k=3)
    assert [h.id for h in hits] == ["a", "c", "b"]  # 余弦相似度排序：a 最接近查询
    assert hits[0].payload == {"doc_id": "d1"}
    assert 0.99 < hits[0].score <= 1.0  # 同向量余弦 = 1


def test_search_unknown_collection_returns_empty():
    store = BruteForceVectorStore()
    assert store.search("nope", [1.0, 0.0]) == []  # 集合不存在不崩溃


def test_search_empty_collection_returns_empty():
    store = BruteForceVectorStore()
    store.create_collection("c", dim=2)
    assert store.search("c", [1.0, 0.0]) == []


def test_dim_mismatch_rejected():
    store = BruteForceVectorStore()
    store.create_collection("c", dim=3)
    try:
        store.insert("c", ["a"], [[1.0, 0.0]])
    except ValueError:
        pass
    else:
        raise AssertionError("向量维度不一致应抛 ValueError")
    try:
        store.search("c", [1.0, 0.0])
    except ValueError:
        pass
    else:
        raise AssertionError("查询维度不一致应抛 ValueError")


def test_insert_before_create_raises():
    store = BruteForceVectorStore()
    try:
        store.insert("c", ["a"], [[1.0]])
    except KeyError:
        pass
    else:
        raise AssertionError("未 create_collection 就 insert 应抛 KeyError")


def test_persist_roundtrip(tmp_path):
    path = tmp_path / "vectors.json"
    store = BruteForceVectorStore(str(path))
    store.create_collection("c", dim=2)
    store.insert("c", ["x"], [[1.0, 0.0]], [{"src": "s"}])

    reloaded = BruteForceVectorStore(str(path))
    hits = reloaded.search("c", [1.0, 0.0])
    assert hits[0].id == "x"
    assert hits[0].payload == {"src": "s"}


def test_drop_collection():
    store = BruteForceVectorStore()
    store.create_collection("c", dim=2)
    store.drop_collection("c")
    assert store.search("c", [1.0, 0.0]) == []
