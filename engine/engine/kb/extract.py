"""LLM 辅助抽取实体关系（ARD §5 知识入库 / D6）。

把 chunk 文本 → LLM 抽取（实体 + 关系）→ 人工审核 → 入图。
抽取严格限定在 schema 内（label / 关系 / 属性列）——LLM 幻觉出 schema 外的
一律过滤。强 schema 红线：入库不动态加列，抽出的内容必须能落 Ladybug 建好的表。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..platform.graph import SchemaDef
from .chunking import Chunk
from .llm import LLMProtocol

SYSTEM_PROMPT = """你是工业知识图谱抽取器。从给定文本抽取实体和关系，只抽取文本明确表达的。
输出 JSON 对象，格式严格如下：
{"entities": [{"label": "节点类型", "id": "唯一标识", "name": "显示名", "props": {"属性名": 值}}],
 "relationships": [{"src_id": "起点id", "rel": "关系类型", "dst_id": "终点id"}]}
要求：
1. 节点类型、关系类型、属性名必须来自允许列表，禁止自造。
2. id 用文本中的稳定标识（型号/编号/名称），没有则用拼音或规范名。
3. props 只放文本明确给出的属性，类型必须是数字或布尔或字符串。
4. 拿不准的不要抽，宁可少抽不可错抽。
"""


@dataclass
class Entity:
    """抽取出的实体（label/id/props 已过滤到 schema 内）。"""

    label: str
    id: str
    props: dict[str, Any] = field(default_factory=dict)
    name: str = ""


@dataclass
class Relationship:
    """抽取出的关系（src/dst 的 label 由 schema 关系类型唯一确定）。"""

    src_id: str
    rel: str
    dst_id: str

    src_label: str = ""
    dst_label: str = ""


@dataclass
class ExtractionResult:
    """一块的抽取产物（供人工审核；error 非空表示该块抽取失败）。"""

    chunk_id: str
    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    raw_output: str = ""  # LLM 原始输出（审核留痕）
    error: str = ""


class LLExtractor:
    """DeepSeek 抽取器：schema 限定 + JSON 输出 + 幻觉过滤。"""

    def __init__(self, llm: LLMProtocol, schema: SchemaDef):
        self._llm = llm
        self._allowed_labels = {n.label for n in schema.nodes}
        self._node_props = {n.label: set(n.props) for n in schema.nodes}
        self._rel_def = {r.label: (r.src, r.dst) for r in schema.rels}

    def extract(self, chunk: Chunk) -> ExtractionResult:
        """对一块文本抽取三元组。LLM 失败 / 输出非法 → error 标记（审核可见，不静默丢弃）。"""
        prompt = self._build_prompt(chunk)
        try:
            raw = self._llm.chat(system=SYSTEM_PROMPT, user=prompt, json_mode=True)
        except Exception as e:  # 网络/鉴权/超时等——离线流程不崩溃，交审核处理
            return ExtractionResult(chunk.id, error=f"LLM 调用失败: {e}")
        return self._parse(chunk.id, raw)

    # ---- 解析与过滤 ----

    def _parse(self, chunk_id: str, raw: str) -> ExtractionResult:
        data = self._extract_json(raw)
        if data is None:
            return ExtractionResult(chunk_id, raw_output=raw, error="输出不是合法 JSON 对象")
        entities = [e for e in (self._sanitize_entity(e) for e in data.get("entities", [])) if e]
        rels = [r for r in (self._sanitize_rel(r) for r in data.get("relationships", [])) if r]
        return ExtractionResult(chunk_id, entities, rels, raw)

    def _sanitize_entity(self, e: dict) -> Entity | None:
        label = str(e.get("label", "")).strip()
        if label not in self._allowed_labels:
            return None  # schema 外节点类型 → 丢弃
        eid = str(e.get("id", "")).strip()
        if not eid:
            return None
        name = str(e.get("name", "")).strip()
        allowed = self._node_props[label]
        props = {
            k: v
            for k, v in (e.get("props") or {}).items()
            if k in allowed and k != "id" and isinstance(v, (str, int, float, bool))
        }
        return Entity(label, eid, props, name)

    def _sanitize_rel(self, r: dict) -> Relationship | None:
        rel = str(r.get("rel", "")).strip()
        if rel not in self._rel_def:
            return None  # schema 外关系类型 → 丢弃
        src, dst = str(r.get("src_id", "")).strip(), str(r.get("dst_id", "")).strip()
        if not src or not dst:
            return None
        src_label, dst_label = self._rel_def[rel]
        return Relationship(src, rel, dst, src_label, dst_label)

    # ---- 提示词与 JSON 解析 ----

    def _build_prompt(self, chunk: Chunk) -> str:
        nodes = "、".join(sorted(self._allowed_labels))
        rels = "\n".join(f"- {label}: {src} → {dst}" for label, (src, dst) in self._rel_def.items())
        title = " / ".join(chunk.title_path) if chunk.title_path else "(无标题)"
        return (
            f"允许的节点类型：{nodes}\n"
            f"允许的关系类型（起点 → 终点）：\n{rels}\n\n"
            f"文本来源：{title}（{chunk.source_ref}）\n"
            f"---文本---\n{chunk.text}"
        )

    @staticmethod
    def _extract_json(raw: str) -> dict | None:
        """从 LLM 输出提取 JSON 对象（容忍代码围栏/前后噪音）。"""
        m = re.search(r"\{.*\}", raw.strip(), re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None
