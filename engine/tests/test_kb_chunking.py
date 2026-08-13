"""D6 结构感知切块测试：表格/条款/章节/清单/超大块/LLM 兜底/边界。"""

from __future__ import annotations

from engine import StructureChunker


def chunk_texts(text: str, **kw) -> list[str]:
    return [c.text for c in StructureChunker(**kw).chunk_text(text, "doc")]


def test_section_by_headings():
    text = "# 总则\n第一条内容。\n\n## 范围\n适用于所有设备。\n"
    chunks = StructureChunker().chunk_text(text, "doc")
    assert len(chunks) == 2
    assert chunks[0].title_path == ["总则"]
    assert chunks[1].title_path == ["总则", "范围"]


def test_table_kept_whole():
    text = "| 部件 | 磨损阈值 |\n|---|---|\n| 主轴轴承 | 2.8 |\n| 丝杠 | 3.0 |\n"
    chunks = StructureChunker().chunk_text(text, "doc")
    assert len(chunks) == 1
    assert chunks[0].kind == "table"
    assert "主轴轴承" in chunks[0].text


def test_table_oversized_split_with_header(tmp_path):
    rows = ["| 部件 | 阈值 |"] + [f"| 部件{i} | {i} |" for i in range(200)]
    text = "\n".join(rows)
    chunks = StructureChunker(max_chars=120).chunk_text(text, "doc")
    assert len(chunks) > 1
    # 每块都带表头（可独立阅读），正文行不丢
    all_rows = [c for c in chunks if c.kind == "table"]
    for c in all_rows:
        assert "| 部件 | 阈值 |" in c.text
    assert sum(c.text.count("| 部件") for c in all_rows) >= 200 + 1


def test_clause_items_grouped():
    text = "1. 轴承温度不得超过 70℃。\n2. 润滑油每 500 小时更换。\n3. 异常振动需立即停机。\n"
    chunks = StructureChunker().chunk_text(text, "doc")
    assert len(chunks) == 1
    assert "1. 轴承" in chunks[0].text and "3. 异常" in chunks[0].text


def test_list_grouped_under_heading():
    text = "# 检查项\n- 气密性\n- 表面粗糙度\n- 平行度\n"
    chunks = StructureChunker().chunk_text(text, "doc")
    assert len(chunks) == 1
    assert chunks[0].kind == "list"
    assert chunks[0].title_path == ["检查项"]


def test_oversized_section_split_by_paragraphs():
    para = "设备运行状态必须定期巡检。发现异常立即上报并停机处理。"
    text = "。".join([para] * 100)  # 超长
    chunks = StructureChunker(max_chars=200).chunk_text(text, "doc")
    assert len(chunks) > 1
    assert all(len(c.text) <= 200 for c in chunks)


def test_empty_doc_returns_empty():
    assert StructureChunker().chunk_text("", "doc") == []
    assert StructureChunker().chunk_text("   \n  ", "doc") == []


def test_no_heading_plain_text_single_chunk():
    text = "这段文本没有任何标题结构，就是普通内容。"
    chunks = StructureChunker().chunk_text(text, "doc")
    assert len(chunks) == 1
    assert chunks[0].kind == "section"
    assert chunks[0].title_path == []


def test_llm_fallback_for_unsplittable():
    # 无句读、无空行、超长单行 → 规则拆不动 → LLM 兜底
    text = "X" * 5000
    calls = []

    class FakeSplitter:
        def split(self, t: str) -> list[str]:
            calls.append(t)
            mid = len(t) // 2
            return [t[:mid], t[mid:]]

    chunks = StructureChunker(max_chars=100, llm_splitter=FakeSplitter()).chunk_text(text, "doc")
    assert calls  # LLM 兜底被调用
    assert len(chunks) == 2
    assert all(c.kind == "llm_split" for c in chunks)


def test_llm_fallback_failure_keeps_original():
    class BadSplitter:
        def split(self, t: str) -> list[str]:
            return []  # LLM 拆失败

    text = "Y" * 5000
    chunks = StructureChunker(max_chars=100, llm_splitter=BadSplitter()).chunk_text(text, "doc")
    assert len(chunks) == 1  # 保留原块，不丢内容
    assert chunks[0].text == text


def test_title_root_prefix():
    chunks = StructureChunker().chunk_text("# 第一章\n内容。", "doc", title="手册")
    assert chunks[0].title_path == ["手册", "第一章"]
