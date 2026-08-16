"""LLM 服务（demo 层）：DeepSeek 三职责接入，图（TBox/ABox）约束兜底。

神经-符号（AI proposes, Logic disposes）：
- propose：LLM 提议候选根因，调用方用 TBox 候选集校验（候选必须 ⊆ 症状→故障候选）、
  ABox 证据把关——LLM 提议被图约束，越界即拒绝。
- explain：LLM 把推理链说成人话（fallback 模板）。
- parse：NLU 自然语言事故解析。

稳定性：无 key 或 LLM 调用失败 → 确定性兜底（不阻塞 demo、不硬出结论）。
密钥只从环境变量读取（红线），不落盘。
"""

from __future__ import annotations

import json
import os

from engine.kb.llm import DeepSeekClient

PROPOSE_SYSTEM = (
    "你是工业质量事故根因分析助手。给定端面铣削的工艺信号症状与候选根因集，"
    "你从候选集中挑选最可能的根因（可多个，按可能性排序），并给出理由。"
    "只允许选择候选集中的 id，禁止自造。输出 JSON："
    '{"candidates": [{"id": "候选id", "reason": "理由"}]}'
)

EXPLAIN_SYSTEM = (
    "你是工业质量事故溯源 Agent 的人话表达层。把给定的推理链（检测/归因/责任/证据）"
    "用专业、简洁、可信的中文讲成一段溯源报告，按推理顺序组织，引用具体证据数值，"
    "不要编造证据之外的结论。"
)

PARSE_SYSTEM = (
    "你是工业质检报告解析器。把自然语言事故报告解析为结构化事件。"
    "输出 JSON："
    '{"part_id": "零件编号", "entity_ref": "对象id", "failed_indicators": ["不合格指标"], '
    '"raw_ref": "报告原文摘要"}'
)


class LLMService:
    """DeepSeek 三职责封装；无 key / 失败 → enabled=False，调用方走确定性兜底。"""

    def __init__(self, api_key: str | None = None, timeout: float = 40.0):
        self._client: DeepSeekClient | None = None
        self._timeout = timeout
        key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if key:
            try:
                self._client = DeepSeekClient(key, timeout=timeout)
            except Exception:
                self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    # ---- 探索提议（图约束在调用方校验）----

    def propose_causes(self, symptom: str, signal_desc: str, allowed: list[str]) -> list[str]:
        """LLM 提议候选根因；只返回候选集内的 id（越界由本层过滤）。"""
        if self._client is None:
            return allowed  # 无 LLM → TBox 全候选兜底
        prompt = (
            f"症状：{symptom}\n信号证据：{signal_desc}\n候选根因集（只能从中选）："
            f"{json.dumps(allowed, ensure_ascii=False)}\n请挑选最可能的根因。"
        )
        try:
            raw = self._client.chat(PROPOSE_SYSTEM, prompt, json_mode=True)
            data = self._extract_json(raw)
            picked = [str(c["id"]) for c in data.get("candidates", [])]
            # 图约束：只保留候选集内的（LLM 越界提议被拒绝）
            return [p for p in picked if p in allowed] or allowed
        except Exception:
            return allowed  # LLM 失败 → TBox 全候选兜底

    # ---- 人话表达（fallback 模板在调用方）----

    def explain(self, context: str) -> str | None:
        """LLM 生成溯源报告人话；失败返回 None（调用方用模板兜底）。"""
        if self._client is None:
            return None
        try:
            return self._client.chat(EXPLAIN_SYSTEM, context, json_mode=False).strip()
        except Exception:
            return None

    # ---- 问答 ----

    def ask(self, question: str, system_context: str) -> str | None:
        """Agent 对话框问答：LLM 基于系统上下文回答；失败返回 None。"""
        if self._client is None:
            return None
        try:
            return self._client.chat(system_context, question, json_mode=False).strip()
        except Exception:
            return None

    # ---- NLU 解析 ----

    def parse_accident(self, text: str) -> dict | None:
        """自然语言事故报告 → 结构化事件；失败返回 None。"""
        if self._client is None:
            return None
        try:
            raw = self._client.chat(PARSE_SYSTEM, text, json_mode=True)
            return self._extract_json(raw)
        except Exception:
            return None

    @staticmethod
    def _extract_json(raw: str) -> dict:
        import re

        m = re.search(r"\{.*\}", raw.strip(), re.DOTALL)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
