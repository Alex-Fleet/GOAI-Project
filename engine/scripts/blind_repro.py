"""复现验证：CiP-DMD 层2 盲推发现能否被本体推理复现。

方法：把真实样本（DMC-50H 铣削 ProcessRun）的端面铣削工艺特征写成属性图
Equipment 节点的盲推属性（face_milling_anomalous，由正常工艺窗口判定），
配盲推规则，跑一楼 TracingLoop 完整推理链，看系统推出什么结论。

三个场景（数据见 docs/research/cip-dmd-layer2-blind-rule.md）：
  A 样本 111501（SR=4.49，官方 anomaly=1 原料短，端面铣削空切）：
       盲推检出铣削异常，来料质检合格 → 系统只归设备方向（暴露「质检盲区」缺口）
  B 样本 100101（正常，SR=1.82）：盲推不检出 → 不误报（FAILED）
  C 同 A + 来料侧工艺信号也检出异常（RM1.anomaly=true）→ 系统双向追责
     （证明：要复现「根因在来料」，需要来料侧信号，仅靠质检不够）

用法：python scripts/blind_repro.py [数据目录]   # 默认 /tmp/cipdmd
数据目录缺失时用已知特征值回退（可独立重跑）。
"""

from __future__ import annotations

import csv
import glob
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 允许从任意 cwd 运行

import h5py

from engine import (
    InferenceKernel,
    LadybugGraphStore,
    NluSide,
    Rule,
    SQLiteAudit,
    SQLiteBusinessStore,
    TracingLoop,
    default_schema,
)
from engine.contracts import EvidenceEvent

# 盲推规则窗口（15 个正常样本 min-max，见 research 文档 §2）
WINDOW = {
    "aaCurr6_mean": (2.076, 2.467),
    "aaLoad6_mean": (3.641, 4.382),
}

# 已知特征值回退（数据目录缺失时用；与 /tmp/cipdmd 实测一致）
KNOWN = {
    "111501": (0.07, 1.84),  # 异常1：端面铣削空切（电流/负载极低）
    "100101": (2.47, 3.92),  # 正常
}


def face_milling_stats(data_dir: str, part_id: str) -> tuple[float, float]:
    """从 h5 + timestamp pairs 算 face_milling 子工序的电流/负载均值。"""
    sig = glob.glob(os.path.join(data_dir, "signals", f"{part_id}_*frontside_internal_machine_signals.h5"))
    pairs = glob.glob(os.path.join(data_dir, "csv", f"{part_id}_*frontside_timestamp_process_pairs.csv"))
    if not sig or not pairs:
        if part_id in KNOWN:
            return KNOWN[part_id]
        raise SystemExit(f"缺数据且无已知特征值: part={part_id}, data_dir={data_dir}")
    with h5py.File(sig[0], "r") as hf:
        cols = list(hf["data"].attrs["column_names"])
        arr = hf["data"][:]
    rows = []
    with open(pairs[0]) as f:
        for row in csv.reader(f):
            if len(row) >= 2:
                rows.append((float(row[0]), row[1]))
    t = arr[:, cols.index("timestamp")]
    for i, (ts, name) in enumerate(rows):
        if name != "face_milling":
            continue
        end = rows[i + 1][0] if i + 1 < len(rows) else t[-1]
        mask = (t >= ts) & (t <= end)
        return (
            float((arr[mask, cols.index("aaCurr6")]).mean()),
            float((arr[mask, cols.index("aaLoad6")]).mean()),
        )
    raise SystemExit(f"样本无 face_milling 子工序: part={part_id}")


def is_anomalous(curr6: float, load6: float) -> bool:
    """盲推判定：电流或负载均值越出正常窗口 → 铣削过程异常。"""
    lo_c, hi_c = WINDOW["aaCurr6_mean"]
    lo_l, hi_l = WINDOW["aaLoad6_mean"]
    return curr6 < lo_c or curr6 > hi_c or load6 < lo_l or load6 > hi_l


def _schema():
    schema = default_schema()
    for node in schema.nodes:
        if node.label == "Equipment":
            node.props["face_milling_curr_mean"] = "DOUBLE"
            node.props["face_milling_load_mean"] = "DOUBLE"
            node.props["face_milling_anomalous"] = "BOOLEAN"
        elif node.label == "Material":
            node.props["anomaly"] = "BOOLEAN"
        elif node.label == "Component":
            node.props["wear_level"] = "DOUBLE"
        elif node.label == "Clause":
            node.props["covers"] = "BOOLEAN"
    return schema


def build_graph(graph: LadybugGraphStore, curr6: float, load6: float, mat_anomaly: bool) -> None:
    """构造 CiP-DMD 气缸底铣削工艺图（一楼 5 域，二楼实例化示例）。"""
    anomalous = is_anomalous(curr6, load6)
    nodes = f"""
CREATE (:Product {{id:'P1', name:'cylinder-bottom'}});
CREATE (:Process {{id:'M1', name:'cnc-milling'}});
CREATE (:Process {{id:'S1', name:'saw'}});
CREATE (:Equipment {{id:'DMC-50H', model:'DMC 50H',
    face_milling_curr_mean:{curr6}, face_milling_load_mean:{load6},
    face_milling_anomalous:{str(anomalous).lower()}}});
CREATE (:Equipment {{id:'SAW', model:'Kasto'}});
CREATE (:Material {{id:'RM1', name:'steel-bar', anomaly:{str(mat_anomaly).lower()}}});
CREATE (:Component {{id:'SP1', name:'spindle-bearing', wear_level:3.5}});
CREATE (:Supplier {{id:'SUP-A', name:'Acme'}});
CREATE (:Supplier {{id:'SUP-B', name:'SteelCo'}});
CREATE (:Clause {{id:'CL-1', name:'warranty', covers:true}});
CREATE (:Clause {{id:'CL-2', name:'material-spec', covers:true}});
"""
    rels = """
MATCH (p:Product {id:'P1'}), (m:Process {id:'M1'}) CREATE (p)-[:HAS_PROCESS]->(m);
MATCH (p:Product {id:'P1'}), (s:Process {id:'S1'}) CREATE (p)-[:HAS_PROCESS]->(s);
MATCH (m:Process {id:'M1'}), (e:Equipment {id:'DMC-50H'}) CREATE (m)-[:AT_EQUIPMENT]->(e);
MATCH (s:Process {id:'S1'}), (e:Equipment {id:'SAW'}) CREATE (s)-[:AT_EQUIPMENT]->(e);
MATCH (p:Product {id:'P1'}), (r:Material {id:'RM1'}) CREATE (p)-[:USES_MATERIAL]->(r);
MATCH (e:Equipment {id:'DMC-50H'}), (c:Component {id:'SP1'}) CREATE (e)-[:HAS_COMPONENT]->(c);
MATCH (c:Component {id:'SP1'}), (su:Supplier {id:'SUP-A'}) CREATE (c)-[:SUPPLIED_BY]->(su);
MATCH (r:Material {id:'RM1'}), (su:Supplier {id:'SUP-B'}) CREATE (r)-[:SUPPLIED_MATERIAL]->(su);
MATCH (su:Supplier {id:'SUP-A'}), (cl:Clause {id:'CL-1'}) CREATE (su)-[:SUBJECT_TO]->(cl);
MATCH (su:Supplier {id:'SUP-B'}), (cl:Clause {id:'CL-2'}) CREATE (su)-[:SUBJECT_TO]->(cl);
"""
    for stmt in (nodes + rels).split(";"):
        if stmt.strip():
            graph.execute(stmt.strip())


def build_loop(graph):
    business = SQLiteBusinessStore(":memory:")
    business.upsert("contract-1", "contract", {"supplier": "SUP-A", "orders": ["ORD-1"], "products": ["P-1"]})
    audit = SQLiteAudit(":memory:")
    nlu = NluSide()
    kernel = InferenceKernel(graph, rules=[])
    layer_rules = {
        "L2_equipment": [Rule("face_milling_anomalous", "Equipment", "face_milling_anomalous", "==", True)],
        "L2_material": [Rule("material_anomaly", "Material", "anomaly", "==", True)],
        "L3": [Rule("component_wear", "Component", "wear_level", ">=", 2.8)],
        "L4": [Rule("clause_covers", "Clause", "covers", "==", True)],
    }
    return TracingLoop(kernel, nlu, graph, business, audit, layer_rules)


def run_scenario(name: str, curr6: float, load6: float, mat_anomaly: bool) -> None:
    graph = LadybugGraphStore(":memory:", _schema())
    build_graph(graph, curr6, load6, mat_anomaly)
    loop = build_loop(graph)
    event = EvidenceEvent(
        entity_ref="P1", entity_type="part", ts=0,
        failed_indicators=["surface_roughness"],
        raw_ref="cip-dmd://cylinder_bottom/111501",
    )
    chain = loop.run(event)
    print(f"\n===== 场景 {name}: Curr6={curr6}, Load6={load6}, 来料异常={mat_anomaly} =====")
    print(f"状态: {chain.status}" + (f"  | 原因: {chain.note}" if chain.status == "FAILED" else ""))
    print("步骤:")
    for step in chain.steps:
        v = step.verdict
        desc = f"{v.rule_id}={v.observed} {v.operator} {v.threshold} -> {'通过' if v.passed else '不通过'}" if v else ""
        path = " → ".join(f"{e.src.label}:{e.src.id}-{e.rel}->{e.dst.id}" for e in step.path) or "(无路径)"
        print(f"  [{step.layer}] {desc}  {path}")
    print("责任对象:", chain.impact.get("liabilities"))
    print("处置建议:", [a.description for a in chain.actions])


def main() -> None:
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/cipdmd"
    # 场景 A/B 用真实样本特征（优先从数据算，缺数据回退已知值）
    c6_a, l6_a = face_milling_stats(data_dir, "111501")
    c6_b, l6_b = face_milling_stats(data_dir, "100101")
    run_scenario("A: 111501(来料缺陷) 盲推检出+来料质检合格", c6_a, l6_a, mat_anomaly=False)
    run_scenario("B: 100101(正常) 盲推不检出", c6_b, l6_b, mat_anomaly=False)
    run_scenario("C: 111501 + 来料工艺信号也检出", c6_a, l6_a, mat_anomaly=True)


if __name__ == "__main__":
    main()
