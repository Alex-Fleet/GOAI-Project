"""审计底座：哈希链可独立重算 + 篡改即失效（ARD §5.2）。"""

from __future__ import annotations

from .conftest import make_event


def test_root_hash_present_and_verifiable(service):
    chain = service.start(make_event("P1"))
    assert chain.root_hash
    assert service.verify_chain(chain) is True


def test_tamper_with_step_breaks_chain(service, audit):
    """篡改任一层结论内容 → 独立重算失败（防篡改落地）。"""
    chain = service.start(make_event("P1"))
    assert service.verify_chain(chain) is True
    # 模拟篡改：改写链上某一层的原始内容
    audit._conn.execute("UPDATE chain SET content = 'tampered' WHERE idx = 1")
    audit._conn.commit()
    assert service.verify_chain(chain) is False


def test_tamper_with_trigger_breaks_chain(service, audit):
    """篡改输入指纹 → 根指纹对不上（输入防篡改）。"""
    chain = service.start(make_event("P1"))
    assert service.verify_chain(chain) is True
    audit._trigger_hash = "0" * 64  # 模拟输入指纹被改
    assert service.verify_chain(chain) is False


def test_each_step_has_distinct_hash(service, audit):
    """链上每层哈希互不相同（H(prev + content) 迭代）。"""
    chain = service.start(make_event("P1"))
    rows = audit._conn.execute("SELECT step_hash FROM chain ORDER BY idx").fetchall()
    hashes = [r["step_hash"] for r in rows]
    assert len(hashes) == len(chain.steps)
    assert len(set(hashes)) == len(hashes)  # 无重复
