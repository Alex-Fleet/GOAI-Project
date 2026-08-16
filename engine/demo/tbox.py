"""TBox：气动缸场景的模式层（二楼实例化，不碰一楼 engine/）。

承载三类知识：
1. 盲推窗口——工艺信号 → 症状（Symptom）的判定阈值（从正常样本学得）
2. 候选因果——症状 → 可能原因（Fault 候选）的映射（网的分叉）
3. 组合判定——每个 Fault 的证据规则（多证据综合，ABox 数据判定）

与 ABox 的关系：TBox 是"模式/类"，ABox 是"个体/实例"。归因器用本模块的
模式 + ABox 的具体测量值做候选排除。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. 盲推窗口（15 个正常样本 min-max，见 docs/research/cip-dmd-layer2-blind-rule.md）
# ---------------------------------------------------------------------------

# 盲推窗口（30 个正常样本均值±3σ）：正常误报 3.3%，异常1（来料短）检出 99%。
# 异常2（夹持）与正常工艺信号高度重叠，检出率低（本质难检）——demo 归因用排除法，不依赖检出。
CURR6_WINDOW = (1.49, 3.39)  # 端面铣削主轴电流均值
LOAD6_WINDOW = (2.92, 5.35)  # 端面铣削主轴负载均值
CURR6_PEAK_HIGH = 12.0  # 电流尖峰阈值（超过判过载）

# 来料侧基线（锯切重量）——注意：正常/异常1 重量区间高度重叠（0.51~0.56），
# 单一重量判不了根因（质检盲区本质）。空切信号是主证据，重量是辅助（低于均值增强置信）。
MATERIAL_WEIGHT_BASELINE = 0.569  # 正常平均（异常1 均值 0.546，轻约 4%）
MATERIAL_WEIGHT_LIMIT_LO = 0.495  # 质检合格下限
MATERIAL_WEIGHT_LIMIT_HI = 0.641  # 质检合格上限

SYMPTOM_AIR_CUT = "air_cut"  # 空切（电流极低）
SYMPTOM_OVERLOAD = "overload"  # 过载（电流偏高/尖峰）
SYMPTOM_NORMAL = "normal"

SYMPTOM_NAMES = {
    SYMPTOM_AIR_CUT: "端面铣削空切（电流极低）",
    SYMPTOM_OVERLOAD: "端面铣削过载（电流偏高/尖峰）",
    SYMPTOM_NORMAL: "工艺信号正常",
}


def classify_signal(curr6_mean: float, load6_mean: float, curr6_peak: float) -> str:
    """工艺信号 → 症状（盲推检测）。"""
    if curr6_mean < CURR6_WINDOW[0] or load6_mean < LOAD6_WINDOW[0]:
        return SYMPTOM_AIR_CUT
    if curr6_mean > CURR6_WINDOW[1] or load6_mean > LOAD6_WINDOW[1] or curr6_peak > CURR6_PEAK_HIGH:
        return SYMPTOM_OVERLOAD
    return SYMPTOM_NORMAL


# ---------------------------------------------------------------------------
# 2. 候选因果：症状 → 可能原因（Fault 候选）
# ---------------------------------------------------------------------------

# Fault 标识
FAULT_MATERIAL_SHORT = "material_short"  # 来料尺寸不足
FAULT_CLAMPING = "clamping_error"  # 工件夹持不平
FAULT_TOOL = "tool_error"  # 对刀/程序错误
FAULT_MATERIAL_OVERSIZE = "material_oversize"  # 来料过大

SYMPTOM_CAUSES: dict[str, list[str]] = {
    SYMPTOM_AIR_CUT: [FAULT_MATERIAL_SHORT, FAULT_CLAMPING, FAULT_TOOL],
    SYMPTOM_OVERLOAD: [FAULT_CLAMPING, FAULT_MATERIAL_OVERSIZE],
}

# 候选的中文名（归因结论展示）
FAULT_NAMES = {
    FAULT_MATERIAL_SHORT: "来料尺寸不足（锯切毛坯偏短）",
    FAULT_CLAMPING: "工件夹持不平（设备侧）",
    FAULT_TOOL: "对刀/程序错误",
    FAULT_MATERIAL_OVERSIZE: "来料尺寸过大",
}

# ---------------------------------------------------------------------------
# 3. 组合判定：每个 Fault 的证据规则
# 证据真值由 ABox 数据（信号特征 + 来料测量）算出，全部满足才锁定。
# ---------------------------------------------------------------------------

FAULT_EVIDENCE: dict[str, dict[str, str]] = {
    FAULT_MATERIAL_SHORT: {
        "require_symptom": SYMPTOM_AIR_CUT,
        "material_weight_low": "来料锯切重量低于正常均值（质检盲区：未超线但趋势偏轻）",
        "not_overload": "铣削无过载信号（排除设备侧负载异常）",
    },
    FAULT_CLAMPING: {
        "require_symptom": SYMPTOM_OVERLOAD,
        "material_weight_in_limits": "来料重量在质检合格线内（排除来料方向）",
    },
    FAULT_TOOL: {
        "require_symptom": SYMPTOM_AIR_CUT,
        "material_weight_in_limits": "来料重量在质检合格线内（排除来料方向）",
        "has_tool_signal": "刀具磨损/对刀信号（当前数据无刀具传感器，恒证据不足）",
    },
    FAULT_MATERIAL_OVERSIZE: {
        "require_symptom": SYMPTOM_OVERLOAD,
        "material_weight_above_limit": "来料重量超质检上限（明显过大）",
    },
}


def evidence_names(fault: str) -> dict[str, str]:
    """返回该 Fault 的证据规则（证据名 → 说明）。"""
    return FAULT_EVIDENCE.get(fault, {})
