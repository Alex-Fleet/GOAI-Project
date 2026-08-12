"""分层溯源各层推理（ARD §4.2 7 步链）。

职责边界：本模块只做「探索 + 领域判定」——沿图生成候选、波及前推、处置建议。
候选的「把关」（图验证 + 规则判定）统一由推理核（infer.InferenceKernel）完成，
编排与回溯在 loop.py。层函数只依赖契约与注入的知识/业务数据，不感知具体工厂。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts import (
    Action,
    EdgeRef,
    EvidenceEvent,
    NodeRef,
)


@dataclass
class Candidate:
    """候选：节点 + 到达它的边轨迹（basis，既是回放路径也是把关依据）。"""

    node: NodeRef
    basis: list[EdgeRef] = field(default_factory=list)


def evidence_of(node: NodeRef) -> list[str]:
    """候选节点的图证据引用（哈希链锚点；二楼可挂真实原始证据）。"""
    return [f"graph://{node.label}/{node.id}"]


# ---------------------------------------------------------------------------
# 探索（确定性图遍历生成候选）
# ---------------------------------------------------------------------------


def explore_l1(
    event: EvidenceEvent, graph
) -> tuple[list[Candidate], list[Candidate], list[EdgeRef]]:
    """层1 工艺图定位：Product → Process → Equipment（设备）；Product → Material（外购件）。"""
    product = NodeRef("Product", event.entity_ref)
    all_basis: list[EdgeRef] = []
    devices: list[Candidate] = []
    for pe in graph.query(product, "HAS_PROCESS", "forward"):
        all_basis.append(pe)
        for ee in graph.query(pe.dst, "AT_EQUIPMENT", "forward"):
            all_basis.append(ee)
            devices.append(Candidate(ee.dst, [pe, ee]))
    materials: list[Candidate] = []
    for me in graph.query(product, "USES_MATERIAL", "forward"):
        all_basis.append(me)
        materials.append(Candidate(me.dst, [me]))
    return devices, materials, all_basis


def explore_l3(device: NodeRef, graph) -> list[Candidate]:
    """层3 设备内部：沿 HAS_COMPONENT 下钻部件候选。"""
    return [Candidate(e.dst, [e]) for e in graph.query(device, "HAS_COMPONENT", "forward")]


def explore_supplier(node: NodeRef, rel: str, graph) -> list[Candidate]:
    """层4 供应链：节点 → 供应商，附其条款边（SUBJECT_TO）作为 basis 延伸。"""
    out: list[Candidate] = []
    for se in graph.query(node, rel, "forward"):
        clause_edges = graph.query(se.dst, "SUBJECT_TO", "forward")
        if clause_edges:
            for ce in clause_edges:
                out.append(Candidate(se.dst, [se, ce]))
        else:
            out.append(Candidate(se.dst, [se]))  # 无条款：basis 仅到供应商
    return out


# ---------------------------------------------------------------------------
# 波及前推 / 处置建议
# ---------------------------------------------------------------------------


def assess_impact(liabilities: list[NodeRef], business, event: EvidenceEvent) -> dict:
    """波及前推：责任对象 → 相关成品 / 工单 / 订单 / 合同（业务层查询，二楼填真实台账）。"""
    affected: list[str] = []
    orders: list[str] = []
    contracts: list[str] = []
    for liab in liabilities:
        for rec in business.query({"type": "contract", "supplier": liab.id}):
            contracts.append(str(rec.get("key")))
            orders.extend(str(o) for o in rec.get("orders", []))
            affected.extend(str(p) for p in rec.get("products", []))

    # 去重保序
    def _dedup(seq: list[str]) -> list[str]:
        return list(dict.fromkeys(seq))

    return {
        "liabilities": [liab.id for liab in liabilities],
        "affected_products": _dedup(affected),
        "orders": _dedup(orders),
        "contracts": _dedup(contracts),
        "trigger": event.entity_ref,
    }


def build_actions(
    equipment: NodeRef | None, liabilities: list[NodeRef], impact: dict
) -> list[Action]:
    """处置建议：人确认后由执行层落库（freeze / halt / claim / inspect）。"""
    import uuid

    actions: list[Action] = []
    for product in impact.get("affected_products", []) or []:
        actions.append(
            Action(
                id=f"a-{uuid.uuid4().hex[:8]}",
                action_type="freeze",
                target_ref=str(product),
                description=f"冻结受影响批次/产品 {product}",
            )
        )
    if equipment is not None:
        actions.append(
            Action(
                id=f"a-{uuid.uuid4().hex[:8]}",
                action_type="halt",
                target_ref=equipment.id,
                description=f"停机检修设备 {equipment.id}",
            )
        )
    for liab in liabilities:
        actions.append(
            Action(
                id=f"a-{uuid.uuid4().hex[:8]}",
                action_type="claim",
                target_ref=liab.id,
                description=f"依据条款向供应商 {liab.id} 索赔",
            )
        )
    return actions
