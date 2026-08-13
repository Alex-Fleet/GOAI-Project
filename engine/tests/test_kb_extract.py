"""D6 抽取测试：schema 限定解析 / 幻觉过滤 / 非法输出 / LLM 失败兜底。"""

from __future__ import annotations

import json

from engine import LLExtractor, default_schema
from tests.helpers import StubLLM, make_chunk

EXTRACT_OK = json.dumps(
    {
        "entities": [
            {
                "label": "Equipment",
                "id": "DMC-50H",
                "name": "加工中心",
                "props": {"model": "DMC 50H"},
            },
            {"label": "Component", "id": "C1", "name": "主轴轴承", "props": {}},
        ],
        "relationships": [{"src_id": "DMC-50H", "rel": "HAS_COMPONENT", "dst_id": "C1"}],
    },
    ensure_ascii=False,
)


def test_extract_ok():
    llm = StubLLM(EXTRACT_OK)
    extractor = LLExtractor(llm, default_schema())
    result = extractor.extract(make_chunk("文本"))
    assert result.error == ""
    assert len(result.entities) == 2
    assert result.entities[0].label == "Equipment"
    assert result.entities[0].props == {"model": "DMC 50H"}
    assert result.relationships[0].rel == "HAS_COMPONENT"
    assert result.relationships[0].src_label == "Equipment"
    assert result.relationships[0].dst_label == "Component"


def test_schema_outsider_filtered():
    raw = json.dumps(
        {
            "entities": [
                {"label": "UFO", "id": "x", "name": "不存在类型"},  # schema 外 label → 丢弃
                {
                    "label": "Equipment",
                    "id": "DMC",
                    "name": "m",
                    "props": {"magic": 1},
                },  # schema 外属性 → 过滤
            ],
            "relationships": [
                {"src_id": "a", "rel": "TELEPORTS", "dst_id": "b"},  # schema 外关系 → 丢弃
                {"src_id": "DMC", "rel": "HAS_COMPONENT", "dst_id": "c"},
            ],
        }
    )
    extractor = LLExtractor(StubLLM(raw), default_schema())
    result = extractor.extract(make_chunk("t"))
    assert [e.label for e in result.entities] == ["Equipment"]
    assert result.entities[0].props == {}  # magic 被过滤
    assert result.relationships[0].rel == "HAS_COMPONENT"


def test_missing_id_dropped():
    raw = json.dumps(
        {
            "entities": [{"label": "Equipment", "id": "", "name": "无名"}],
            "relationships": [],
        }
    )
    extractor = LLExtractor(StubLLM(raw), default_schema())
    assert extractor.extract(make_chunk("t")).entities == []


def test_invalid_json_marks_error():
    extractor = LLExtractor(StubLLM("这不是 JSON"), default_schema())
    result = extractor.extract(make_chunk("t"))
    assert result.error
    assert result.entities == [] and result.relationships == []


def test_json_with_code_fence_tolerated():
    raw = "```json\n" + EXTRACT_OK + "\n```"
    extractor = LLExtractor(StubLLM(raw), default_schema())
    result = extractor.extract(make_chunk("t"))
    assert result.error == ""
    assert len(result.entities) == 2


def test_llm_exception_marks_error():
    def boom(system, user, json_mode=False):
        raise RuntimeError("网络超时")

    extractor = LLExtractor(StubLLM(boom), default_schema())
    result = extractor.extract(make_chunk("t"))
    assert "LLM 调用失败" in result.error
    assert result.entities == []


def test_prompt_contains_schema():
    llm = StubLLM(EXTRACT_OK)
    LLExtractor(llm, default_schema()).extract(make_chunk("t"))
    system, user, json_mode = llm.calls[0]
    assert "Equipment" in user and "HAS_COMPONENT" in user  # 允许类型/关系进了提示词
    assert json_mode is True  # 要求 JSON 输出
