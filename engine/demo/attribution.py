"""归因器（二楼）：工艺信号 → 症状 → 候选原因 → 证据排除 → 锁定根因。

执行"AI proposes, Logic disposes"：盲推信号只负责提出症状（空切/过载），
本体候选因果（tbox.SYMPTOM_CAUSES）提供所有可能原因，归因器逐候选验证
证据（tbox.FAULT_EVIDENCE + ABox 真实测量），证据不足的排除，锁定唯一根因。

输出归因结果，供 demo 服务挂接到 TraceChain 展示。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import tbox


@dataclass
class SignalStats:
    """端面铣削工艺信号统计（ABox 个体观测）。"""

    curr6_mean: float
    load6_mean: float
    curr6_peak: float


@dataclass
class AttributionResult:
    """归因结果：症状 + 候选 + 证据判定 + 锁定根因。"""

    part_id: str = ""
    symptom: str = tbox.SYMPTOM_NORMAL
    candidates: list[str] = field(default_factory=list)
    satisfied: list[str] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)  # fault -> 排除原因
    evidence: dict[str, bool] = field(default_factory=dict)  # 证据名 -> 真值
    locked: str | None = None  # 锁定的根因 Fault（None = 无法归因）
    reason: str = ""  # 人话结论

    @property
    def is_anomaly(self) -> bool:
        return self.symptom != tbox.SYMPTOM_NORMAL


class Attributor:
    """归因器：输入信号 + 来料测量 → 归因结论。"""

    def __init__(self, material_weight: float):
        self._mat_w = material_weight  # 该零件的锯切来料重量（kg）

    def attribute(self, part_id: str, sig: SignalStats, candidates: list[str] | None = None) -> AttributionResult:
        symptom = tbox.classify_signal(sig.curr6_mean, sig.load6_mean, sig.curr6_peak)
        res = AttributionResult(part_id=part_id, symptom=symptom)
        if symptom == tbox.SYMPTOM_NORMAL:
            res.reason = "端面铣削工艺信号在正常窗口内，未检出异常。"
            return res

        # 证据真值（ABox 测量判定）
        ev = {
            "material_weight_low": self._mat_w < tbox.MATERIAL_WEIGHT_BASELINE,
            "material_weight_in_limits": (
                tbox.MATERIAL_WEIGHT_LIMIT_LO <= self._mat_w <= tbox.MATERIAL_WEIGHT_LIMIT_HI
            ),
            "material_weight_above_limit": self._mat_w > tbox.MATERIAL_WEIGHT_LIMIT_HI,
            "not_overload": symptom != tbox.SYMPTOM_OVERLOAD,
            "has_tool_signal": False,  # 当前数据无刀具传感器信号 → 对刀证据恒不足
        }
        res.evidence = ev
        # 候选来源：默认 TBox 候选；传入（LLM 提议且已被 TBox 约束）则用传入的
        res.candidates = list(candidates) if candidates else list(tbox.SYMPTOM_CAUSES.get(symptom, []))

        # 逐候选验证证据（排除法）
        for fault in res.candidates:
            rules = tbox.FAULT_EVIDENCE.get(fault, {})
            if rules.get("require_symptom") != symptom:
                res.excluded[fault] = "症状不匹配"
                continue
            # 检查除 require_symptom/note 外的证据规则
            missing = []
            for rule in rules:
                if rule in ("require_symptom", "note"):
                    continue
                if not ev.get(rule, False):
                    missing.append(f"证据不满足:{rules[rule]}")
            if missing:
                res.excluded[fault] = "；".join(missing)
            else:
                res.satisfied.append(fault)

        # 锁定：证据满足的候选（0 个=无法归因；>1 个=无法区分；1 个=锁定）
        if len(res.satisfied) == 1:
            res.locked = res.satisfied[0]
            res.reason = f"检出{tbox.SYMPTOM_NAMES.get(symptom, symptom)}，证据排除后锁定根因：{tbox.FAULT_NAMES[res.locked]}。"
        elif len(res.satisfied) > 1:
            res.reason = f"检出异常，但多个候选（{', '.join(tbox.FAULT_NAMES[f] for f in res.satisfied)}）证据均满足，无法区分——不硬出结论。"
        else:
            res.reason = f"检出{tbox.SYMPTOM_NAMES.get(symptom, symptom)}，但所有候选证据均不满足，无法归因——不硬出结论。"
        return res


def symptom_name(symptom: str) -> str:
    return tbox.SYMPTOM_NAMES.get(symptom, symptom)
