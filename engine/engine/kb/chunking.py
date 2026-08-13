"""结构感知切块（ARD §5 知识入库 / 决策：规则为主 + LLM 兜底）。

切块规则按知识形式定（研究结论，非拍脑袋）：
- 表格   → 整块切（行结构不能拆散）；超大按行组拆、表头随行保留
- 条款   → 按条目切（编号项 + 其正文合成一块）
- 章节   → 按标题切（标题层级记入 title_path）；超长按段落/句子拆
- 清单   → 按语义组切（同一标题下的一组列表项）
- 超大块 → 规则拆不动（单行超长/无句读）→ LLM 兜底二次划分

每块带三重身份：LLM 抽取输入 / 向量检索单位 / 审计锚点（source_ref）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")  # markdown 表头分隔线 |---|---|
LIST_ITEM_RE = re.compile(r"^\s*[-*+]\s+(.*)$|^\s*(\d+)[.)]\s+(.*)$")
SENTENCE_RE = re.compile(r"(?<=[。！？；])")  # 句读切点（中文语料为主）


@dataclass
class Chunk:
    """切块单位：LLM 抽取输入 / 向量检索单位 / 审计锚点三位一体。"""

    id: str
    doc_id: str
    kind: str  # "section" | "table" | "clause" | "list" | "llm_split"
    text: str
    title_path: list[str] = field(default_factory=list)  # 章节路径（可回溯源）
    source_ref: str = ""  # 审计锚点，如 "doc.md#L10"
    meta: dict = field(default_factory=dict)


class ChunkSplitter(Protocol):
    """LLM 兜底能力：把规则拆不动的大文本切成语义完整的子块。"""

    def split(self, text: str) -> list[str]: ...


class StructureChunker:
    """结构感知切块器。规则确定性拆分为主，LLM 只兜规则拆不动的边角。

    边界：空文档 → 空列表；无结构纯文本 → 按标题为根的单 section 拆分；
    单行超长且无 LLM → 截断保底（不崩溃、不丢后续内容）。
    """

    def __init__(self, max_chars: int = 2000, llm_splitter: ChunkSplitter | None = None):
        self._max = max_chars
        self._llm = llm_splitter

    # ---- 主入口 ----

    def chunk_text(self, text: str, doc_id: str, title: str = "") -> list[Chunk]:
        if not text or not text.strip():
            return []

        chunks: list[Chunk] = []
        title_stack: list[str] = [title] if title else []
        buf: list[tuple[int, str]] = []  # (lineno, raw_line)
        buf_kind: str | None = None

        def flush() -> None:
            nonlocal buf, buf_kind
            if not buf:
                return
            kind = buf_kind or "section"
            block = "\n".join(line for _, line in buf)
            self._emit(chunks, doc_id, kind, block, title_stack, buf[0][0])
            buf, buf_kind = [], None

        for lineno, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if not line:
                flush()
                continue
            m = HEADING_RE.match(line)
            if m:
                flush()
                level = len(m.group(1))
                # 栈索引 = level（位置 0 留给 title 根；无 title 时 level=1 从栈顶开始）
                title_stack = title_stack[:level] + [m.group(2).strip()]
                continue
            kind = self._classify(line)
            if buf_kind is None:
                buf_kind, buf = kind, [(lineno, raw)]
            elif buf_kind == kind:
                buf.append((lineno, raw))
            else:  # 块类型切换（表格→正文等）→ 切块
                flush()
                buf_kind, buf = kind, [(lineno, raw)]
        flush()
        return chunks

    # ---- 行分类 ----

    @staticmethod
    def _classify(line: str) -> str:
        if TABLE_ROW_RE.match(line):
            return "table"
        if LIST_ITEM_RE.match(line):
            return "list"
        return "section"

    # ---- 切块与超大拆分 ----

    def _emit(self, chunks, doc_id, kind, block, title_stack, start_lineno) -> None:
        pieces = self._split_block(block, kind)
        for i, piece in enumerate(pieces):
            if not piece.strip():
                continue
            final_pieces, out_kind = self._maybe_llm_split(piece), kind
            if out_kind == kind and final_pieces != [piece]:
                out_kind = "llm_split"
            for j, p in enumerate(final_pieces):
                if not p.strip():
                    continue
                suffix = f".{j}" if len(final_pieces) > 1 else ""
                chunks.append(
                    Chunk(
                        id=f"{doc_id}:{start_lineno}:{i}{suffix}",
                        doc_id=doc_id,
                        kind=out_kind,
                        text=p,
                        title_path=list(title_stack),
                        source_ref=f"{doc_id}#L{start_lineno}",
                    )
                )

    def _split_block(self, block: str, kind: str) -> list[str]:
        if len(block) <= self._max:
            return [block]
        if kind == "table":
            return self._split_table(block)
        if kind == "list":
            return self._split_items(block)
        return self._split_section(block)

    def _split_table(self, block: str) -> list[str]:
        """表头 + 分隔线固定随行，正文每满一屏拆一组。"""
        lines = block.splitlines()
        header = [lines[0]]
        body = lines[1:]
        if body and TABLE_SEP_RE.match(body[0]):
            header.append(body[0])
            body = body[1:]
        groups: list[list[str]] = []
        cur = list(header)
        for line in body:
            if cur != header and len("\n".join(cur)) + len(line) + 1 > self._max:
                groups.append(cur)
                cur = list(header)
            cur.append(line)
        if cur != header:
            groups.append(cur)
        return ["\n".join(g) for g in groups]

    def _split_items(self, block: str) -> list[str]:
        """按列表项拆，再把小项合并到接近 max；单项仍超大按句子拆。"""
        lines = block.splitlines()
        items: list[list[str]] = []
        cur: list[str] = []
        for line in lines:
            if LIST_ITEM_RE.match(line) and cur:
                items.append(cur)
                cur = []
            cur.append(line)
        if cur:
            items.append(cur)
        groups: list[list[str]] = []
        cur_group: list[str] = []
        for item in items:
            if cur_group and len("\n".join(cur_group)) + len("\n".join(item)) > self._max:
                groups.append(cur_group)
                cur_group = []
            cur_group.extend(item)
        if cur_group:
            groups.append(cur_group)
        out: list[str] = []
        for g in groups:
            text = "\n".join(g)
            out.extend(self._split_section(text) if len(text) > self._max else [text])
        return out

    def _split_section(self, block: str) -> list[str]:
        """段落（空行）→ 句子，合并相邻小段，直到 < max。"""
        paras = [p.strip() for p in re.split(r"\n\s*\n", block) if p.strip()]
        if not paras:
            paras = [block]
        groups: list[str] = []
        cur = ""
        for p in paras:
            if cur and len(cur) + len(p) + 1 > self._max:
                groups.append(cur)
                cur = ""
            if len(p) > self._max:
                if cur:
                    groups.append(cur)
                    cur = ""
                groups.extend(self._split_sentences(p))
            else:
                cur = f"{cur}\n{p}" if cur else p
        if cur:
            groups.append(cur)
        return groups

    def _split_sentences(self, para: str) -> list[str]:
        parts = SENTENCE_RE.split(para)
        groups: list[str] = []
        cur = ""
        for s in parts:
            if cur and len(cur) + len(s) + 1 > self._max:
                groups.append(cur)
                cur = ""
            cur = f"{cur}{s}"
        if cur:
            groups.append(cur)
        return groups  # 单句仍超长 → 交给 _maybe_llm_split（规则拆不动，不在此截断）

    # ---- LLM 兜底 ----

    def _maybe_llm_split(self, piece: str) -> list[str]:
        if len(piece) <= self._max:
            return [piece]
        if self._llm is not None:
            parts = [p for p in self._llm.split(piece) if p.strip()]
            if parts:
                return parts
        return [piece]  # 无 LLM 或 LLM 拆失败 → 保留原块（不丢内容，宁可块略超长）
