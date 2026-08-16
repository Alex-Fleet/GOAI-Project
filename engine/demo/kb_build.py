"""知识入库（二楼）：知识文档 → 树（切块器）→ 枝桠连接 → TBox/ABox 入图。

流程（用户指定）：
1. 树——StructureChunker 把知识文档切成章节树（title_path 记层级）
2. 枝桠连接——各章节抽取的实体跨文档通过关系连成网（工艺图/因果/供应链）
3. 入图——MERGE 进 Ladybug 属性图（ABox 实例），TBox 模式由 tbox.py 承载

一楼红线：本模块属于二楼实例化，不修改 engine/engine/ 任何文件；
只消费一楼通用 LadybugGraphStore 与 schema。
"""

from __future__ import annotations

from pathlib import Path

from engine import LadybugGraphStore, StructureChunker, default_schema
from engine.platform.graph import NodeTypeDef, RelTypeDef

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

# ---------------------------------------------------------------------------
# 1. 树：知识文档 → StructureChunker 切块
# ---------------------------------------------------------------------------


def chunk_knowledge() -> list:
    """用一楼 StructureChunker 切全部知识文档，返回 chunk 列表（树结构）。"""
    chunker = StructureChunker(max_chars=1500)
    all_chunks = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        doc_id = path.stem
        text = path.read_text(encoding="utf-8")
        chunks = chunker.chunk_text(text, doc_id, title=doc_id)
        all_chunks.extend(chunks)
    return all_chunks


def print_knowledge_tree() -> None:
    """打印知识树的切块结果（展示：文档 → 树）。"""
    chunks = chunk_knowledge()
    print(f"=== 知识文档切块：{len(chunks)} 块 ===")
    for c in chunks:
        title = " / ".join(c.title_path)
        head = c.text.splitlines()[0][:40] if c.text else ""
        print(f"  [{c.kind:7}] {title}  |  {head}...")


# ---------------------------------------------------------------------------
# 2. 枝桠连接 + 3. 入图：气动缸场景图数据（ABox 实例 + TBox 候选因果）
# ---------------------------------------------------------------------------


def demo_schema():
    """一楼通用 schema + 二楼实例属性列 + 二楼关系扩展。

    一楼 HAS_SYMPTOM 定义是 Component→Symptom（部件级症状）；设备级工艺症状
    （空切/过载）用二楼新增关系 EQUIPMENT_HAS_SYMPTOM（Equipment→Symptom）。
    只新增，不改一楼既有定义（红线）。
    """
    schema = default_schema()
    schema.rels.append(RelTypeDef("EQUIPMENT_HAS_SYMPTOM", "Equipment", "Symptom"))
    # 深度本体：参数节点（材料应力/强度/硬度、设备参数、工艺参数）
    schema.nodes.append(
        NodeTypeDef("Property", {"id": "STRING", "name": "STRING", "value": "STRING", "unit": "STRING"})
    )
    schema.rels.append(RelTypeDef("MAT_HAS_PROPERTY", "Material", "Property"))
    schema.rels.append(RelTypeDef("COMP_HAS_PROPERTY", "Component", "Property"))
    schema.rels.append(RelTypeDef("PROC_HAS_PROPERTY", "Process", "Property"))
    schema.rels.append(RelTypeDef("HAS_MATERIAL", "Product", "Material"))
    schema.rels.append(RelTypeDef("COMPONENT_MATERIAL", "Component", "Material"))
    # 业务层本体（合同/订单/客户/违约）+ 深挖（传感器/参数状态）
    schema.nodes.append(NodeTypeDef("Contract", {"id": "STRING", "name": "STRING", "penalty_rate": "DOUBLE"}))
    schema.nodes.append(NodeTypeDef("PurchaseOrder", {"id": "STRING", "name": "STRING", "amount": "DOUBLE"}))
    schema.nodes.append(NodeTypeDef("Customer", {"id": "STRING", "name": "STRING"}))
    schema.rels.append(RelTypeDef("HAS_CONTRACT", "Supplier", "Contract"))
    schema.rels.append(RelTypeDef("COVERS_ORDER", "Contract", "PurchaseOrder"))
    schema.rels.append(RelTypeDef("PLACED_BY", "PurchaseOrder", "Customer"))
    schema.rels.append(RelTypeDef("ORDERS_PRODUCT", "PurchaseOrder", "Product"))
    schema.rels.append(RelTypeDef("MEASURES", "Component", "Property"))
    schema.rels.append(RelTypeDef("PARAM_INDICATES", "Property", "Symptom"))
    schema.rels.append(RelTypeDef("EQUIPMENT_HAS_STANDARD", "Equipment", "Property"))
    schema.rels.append(RelTypeDef("COMPONENT_HAS_COMPONENT", "Component", "Component"))
    # 网状关系（横向）：参数关联 / 部件驱动 / 工序用部件 / 故障级联
    schema.rels.append(RelTypeDef("EQUIPMENT_HAS_PARAM", "Equipment", "Property"))
    schema.rels.append(RelTypeDef("PARAM_AFFECTS", "Property", "Property"))
    schema.rels.append(RelTypeDef("PART_DRIVES", "Component", "Component"))
    schema.rels.append(RelTypeDef("PROCESS_USES", "Process", "Component"))
    schema.rels.append(RelTypeDef("FAULT_CAUSES", "Fault", "Fault"))
    schema.rels.append(RelTypeDef("HAS_PART", "Product", "Product"))
    for node in schema.nodes:
        if node.label == "Equipment":
            node.props["face_milling_curr_mean"] = "DOUBLE"
            node.props["face_milling_load_mean"] = "DOUBLE"
            node.props["face_milling_curr_peak"] = "DOUBLE"
            node.props["face_milling_anomalous"] = "BOOLEAN"
            node.props["symptom"] = "STRING"  # air_cut | overload | normal
        elif node.label == "Material":
            node.props["weight"] = "DOUBLE"
            node.props["weight_below_baseline"] = "BOOLEAN"
        elif node.label == "Component":
            node.props["wear_level"] = "DOUBLE"
        elif node.label == "Clause":
            node.props["covers"] = "BOOLEAN"
    return schema


# 图数据（结构化，供 build_graph 建图 + export_ontology 可视化导出）
# 深度本体：产品 → 材质(参数成节点) / 工艺(参数成节点) → 设备 → 设备内部子系统/部件(参数成节点)。
# 每个设备往下展开成子图；材料参数（应力/强度/硬度）为独立 Property 节点。
# demo 推理链涉及的 id 固定不变（P1/S1/M1/DMC-50H/RM1/SP1/SUP-A/SUP-B/CL-1/CL-2/因果链）。

# --- 节点 ---
NODE_SPECS: list[tuple[str, str, dict]] = [
    # 产品
    ("Product", "P1", {"name": "气缸底 cylinder-bottom"}),
    ("Product", "P2", {"name": "活塞杆 piston-rod"}),
    # 材质
    ("Material", "MAT-CB", {"name": "45# 结构钢（气缸底）"}),
    ("Material", "MAT-PR", {"name": "40Cr 合金钢（活塞杆）"}),
    ("Material", "MAT-BE", {"name": "GCr15 轴承钢"}),
    ("Material", "MAT-TOOL", {"name": "YG6 硬质合金（刀具）"}),
    ("Material", "RM1", {"name": "钢棒毛坯 steel-bar"}),
    # 材料参数（应力/强度/硬度等，独立节点）
    ("Property", "PR-CB-YIELD", {"name": "屈服强度", "value": "355", "unit": "MPa"}),
    ("Property", "PR-CB-TENSILE", {"name": "抗拉强度", "value": "600", "unit": "MPa"}),
    ("Property", "PR-CB-HARDNESS", {"name": "硬度", "value": "180", "unit": "HB"}),
    ("Property", "PR-CB-MODULUS", {"name": "弹性模量", "value": "210", "unit": "GPa"}),
    ("Property", "PR-CB-STRESS", {"name": "工作应力", "value": "80", "unit": "MPa"}),
    ("Property", "PR-CB-FATIGUE", {"name": "疲劳极限", "value": "200", "unit": "MPa"}),
    ("Property", "PR-PR-YIELD", {"name": "屈服强度", "value": "785", "unit": "MPa"}),
    ("Property", "PR-PR-TENSILE", {"name": "抗拉强度", "value": "980", "unit": "MPa"}),
    ("Property", "PR-PR-HARDNESS", {"name": "硬度", "value": "28", "unit": "HRC"}),
    ("Property", "PR-PR-QUENCH", {"name": "淬火深度", "value": "2", "unit": "mm"}),
    ("Property", "PR-BE-HARDNESS", {"name": "硬度", "value": "62", "unit": "HRC"}),
    ("Property", "PR-BE-FATIGUE", {"name": "接触疲劳强度", "value": "1800", "unit": "MPa"}),
    ("Property", "PR-BE-CONTACT", {"name": "许用接触应力", "value": "1400", "unit": "MPa"}),
    ("Property", "PR-TOOL-HARDNESS", {"name": "硬度", "value": "90", "unit": "HRA"}),
    ("Property", "PR-TOOL-WEAR", {"name": "耐磨性", "value": "1.5", "unit": "×"}),
    ("Property", "PR-TOOL-EDGES", {"name": "刀齿数", "value": "6", "unit": "刃"}),
    # 工序
    ("Process", "S1", {"name": "锯切 saw"}),
    ("Process", "M1", {"name": "端面铣削 milling"}),
    ("Process", "L1", {"name": "车削 lathe"}),
    ("Process", "A1", {"name": "装配 assembly"}),
    # 工艺参数
    ("Property", "PR-M1-RPM", {"name": "主轴转速", "value": "12000", "unit": "rpm"}),
    ("Property", "PR-M1-FEED", {"name": "进给率", "value": "800", "unit": "mm/min"}),
    ("Property", "PR-M1-DEPTH", {"name": "切削深度", "value": "2.5", "unit": "mm"}),
    ("Property", "PR-M1-COOL", {"name": "冷却液", "value": "乳化液", "unit": "5%"}),
    ("Property", "PR-S1-SPEED", {"name": "锯切速度", "value": "60", "unit": "m/min"}),
    ("Property", "PR-L1-RPM", {"name": "车削转速", "value": "1500", "unit": "rpm"}),
    ("Property", "PR-L1-FEED", {"name": "进给量", "value": "0.15", "unit": "mm/r"}),
    # 设备
    ("Equipment", "SAW", {"model": "Kasto-SBA2 锯床"}),
    ("Equipment", "DMC-50H", {"model": "DMC 50H 五轴加工中心"}),
    ("Equipment", "C65", {"model": "Index C65 车床"}),
    ("Equipment", "ASSY", {"model": "装配站"}),
    # DMC-50H 内部子系统
    ("Component", "SP-SPINDLE", {"name": "主轴系统"}),
    ("Component", "SP-FEED", {"name": "进给系统"}),
    ("Component", "SP-COOL", {"name": "冷却系统"}),
    ("Component", "SP-MAG", {"name": "刀库"}),
    ("Component", "SP-FIX", {"name": "夹具系统"}),
    # 主轴系统部件
    ("Component", "SP1", {"name": "主轴轴承", "wear_level": 3.5}),
    ("Component", "SP2", {"name": "主轴电机"}),
    # 进给系统部件
    ("Component", "SP3", {"name": "滚珠丝杠"}),
    ("Component", "SP4", {"name": "直线导轨"}),
    ("Component", "SP5", {"name": "伺服电机"}),
    # 刀库部件
    ("Component", "TL1", {"name": "端面铣刀"}),
    ("Component", "TL2", {"name": "钻头"}),
    # 其他设备部件
    ("Component", "BLADE", {"name": "锯条"}),
    ("Component", "LATHE-SP", {"name": "车床主轴"}),
    ("Component", "TOOLPOST", {"name": "刀架"}),
    # 部件参数
    ("Property", "PR-MOTOR-PWR", {"name": "主轴功率", "value": "15", "unit": "kW"}),
    ("Property", "PR-MOTOR-RPM", {"name": "额定转速", "value": "8000", "unit": "rpm"}),
    ("Property", "PR-SCREW-PITCH", {"name": "丝杠导程", "value": "12", "unit": "mm"}),
    ("Property", "PR-SCREW-GRADE", {"name": "精度等级", "value": "P4", "unit": ""}),
    ("Property", "PR-RAIL-STRAIGHT", {"name": "直线度", "value": "0.005", "unit": "mm"}),
    ("Property", "PR-RAIL-LOAD", {"name": "承载", "value": "800", "unit": "kg"}),
    ("Property", "PR-SERVO-TORQ", {"name": "伺服扭矩", "value": "12", "unit": "Nm"}),
    ("Property", "PR-FIX-FORCE", {"name": "夹持力", "value": "20", "unit": "kN"}),
    ("Property", "PR-FIX-POS", {"name": "定位精度", "value": "0.01", "unit": "mm"}),
    ("Property", "PR-COOL-PRES", {"name": "冷却压力", "value": "6", "unit": "bar"}),
    ("Property", "PR-BLADE-PITCH", {"name": "锯条齿距", "value": "6.3", "unit": "mm"}),
    ("Property", "PR-LSP-PWR", {"name": "车床功率", "value": "18", "unit": "kW"}),
    ("Property", "PR-TL1-DIA", {"name": "铣刀直径", "value": "50", "unit": "mm"}),
    # 供应商 / 条款 / 合同 / 订单 / 客户
    ("Supplier", "SUP-A", {"name": "Acme 轴承"}),
    ("Supplier", "SUP-B", {"name": "SteelCo 钢材"}),
    ("Clause", "CL-1", {"name": "轴承质保条款", "covers": True}),
    ("Clause", "CL-2", {"name": "钢材规格条款", "covers": True}),
    ("Contract", "CT-A", {"name": "轴承采购合同", "penalty_rate": 0.15}),
    ("Contract", "CT-B", {"name": "钢材采购合同", "penalty_rate": 0.20}),
    ("PurchaseOrder", "ORD-1", {"name": "轴承订单", "amount": 450000}),
    ("PurchaseOrder", "ORD-2", {"name": "钢材订单", "amount": 1200000}),
    ("Customer", "CUST-1", {"name": "最终客户（主机厂）"}),
    # 深挖：测量传感器 + 参数标准/状态
    ("Component", "SENSOR-RPM", {"name": "主轴转速传感器"}),
    ("Component", "SENSOR-LOAD", {"name": "主轴负载传感器"}),
    ("Property", "PR-M1-RPM-STD", {"name": "标准转速", "value": "12000±200", "unit": "rpm"}),
    ("Symptom", "SYM-RPM-HIGH", {"name": "转速过高"}),
    ("Symptom", "SYM-RPM-LOW", {"name": "转速过低"}),
    # 症状 / 故障 / 缺陷
    ("Symptom", "SYM-AIRCUT", {"name": "端面空切"}),
    ("Symptom", "SYM-OVERLOAD", {"name": "切削过载"}),
    ("Symptom", "SYM-VIBRATION", {"name": "振动"}),
    ("Symptom", "SYM-NOISE", {"name": "异响"}),
    ("Fault", "F-MAT-SHORT", {"name": "来料尺寸不足"}),
    ("Fault", "F-CLAMP", {"name": "夹持不平"}),
    ("Fault", "F-TOOL", {"name": "对刀/程序错误"}),
    ("Fault", "F-MAT-OVER", {"name": "来料尺寸过大"}),
    ("Fault", "F-BEARING-WEAR", {"name": "轴承磨损"}),
    ("Fault", "F-FEED-ERROR", {"name": "进给误差"}),
    ("Defect", "D-SURFACE", {"name": "表面粗糙"}),
    ("Defect", "D-PARALLEL", {"name": "平行度超差"}),
    ("Defect", "D-COAXIAL", {"name": "同轴度超差"}),
    ("Defect", "D-SIZE", {"name": "尺寸偏差"}),
]

# --- 边 ---
EDGE_SPECS: list[tuple[str, str, str]] = [
    # 产品 → 材质（材料参数成节点）
    ("P1", "HAS_MATERIAL", "MAT-CB"),
    ("P2", "HAS_MATERIAL", "MAT-PR"),
    ("MAT-CB", "MAT_HAS_PROPERTY", "PR-CB-YIELD"),
    ("MAT-CB", "MAT_HAS_PROPERTY", "PR-CB-TENSILE"),
    ("MAT-CB", "MAT_HAS_PROPERTY", "PR-CB-HARDNESS"),
    ("MAT-CB", "MAT_HAS_PROPERTY", "PR-CB-MODULUS"),
    ("MAT-CB", "MAT_HAS_PROPERTY", "PR-CB-STRESS"),
    ("MAT-CB", "MAT_HAS_PROPERTY", "PR-CB-FATIGUE"),
    ("MAT-PR", "MAT_HAS_PROPERTY", "PR-PR-YIELD"),
    ("MAT-PR", "MAT_HAS_PROPERTY", "PR-PR-TENSILE"),
    ("MAT-PR", "MAT_HAS_PROPERTY", "PR-PR-HARDNESS"),
    ("MAT-PR", "MAT_HAS_PROPERTY", "PR-PR-QUENCH"),
    ("MAT-BE", "MAT_HAS_PROPERTY", "PR-BE-HARDNESS"),
    ("MAT-BE", "MAT_HAS_PROPERTY", "PR-BE-FATIGUE"),
    ("MAT-BE", "MAT_HAS_PROPERTY", "PR-BE-CONTACT"),
    ("MAT-TOOL", "MAT_HAS_PROPERTY", "PR-TOOL-HARDNESS"),
    ("MAT-TOOL", "MAT_HAS_PROPERTY", "PR-TOOL-WEAR"),
    ("MAT-TOOL", "MAT_HAS_PROPERTY", "PR-TOOL-EDGES"),
    # 产品 → 工序 → 设备
    ("P1", "HAS_PROCESS", "S1"),
    ("P1", "HAS_PROCESS", "M1"),
    ("P2", "HAS_PROCESS", "L1"),
    ("S1", "AT_EQUIPMENT", "SAW"),
    ("M1", "AT_EQUIPMENT", "DMC-50H"),
    ("L1", "AT_EQUIPMENT", "C65"),
    # 工序 → 工艺参数
    ("M1", "PROC_HAS_PROPERTY", "PR-M1-RPM"),
    ("M1", "PROC_HAS_PROPERTY", "PR-M1-FEED"),
    ("M1", "PROC_HAS_PROPERTY", "PR-M1-DEPTH"),
    ("M1", "PROC_HAS_PROPERTY", "PR-M1-COOL"),
    ("S1", "PROC_HAS_PROPERTY", "PR-S1-SPEED"),
    ("L1", "PROC_HAS_PROPERTY", "PR-L1-RPM"),
    ("L1", "PROC_HAS_PROPERTY", "PR-L1-FEED"),
    # DMC-50H 内部子系统 + 关键判断部件（轴承 SP1 保留直接连接，供 L3 下钻判定）
    ("DMC-50H", "HAS_COMPONENT", "SP-SPINDLE"),
    ("DMC-50H", "HAS_COMPONENT", "SP-FEED"),
    ("DMC-50H", "HAS_COMPONENT", "SP-COOL"),
    ("DMC-50H", "HAS_COMPONENT", "SP-MAG"),
    ("DMC-50H", "HAS_COMPONENT", "SP-FIX"),
    ("DMC-50H", "HAS_COMPONENT", "SP1"),
    # 子系统 → 部件
    ("SP-SPINDLE", "HAS_COMPONENT", "SP1"),
    ("SP-SPINDLE", "HAS_COMPONENT", "SP2"),
    ("SP-FEED", "HAS_COMPONENT", "SP3"),
    ("SP-FEED", "HAS_COMPONENT", "SP4"),
    ("SP-FEED", "HAS_COMPONENT", "SP5"),
    ("SP-MAG", "HAS_COMPONENT", "TL1"),
    ("SP-MAG", "HAS_COMPONENT", "TL2"),
    # 部件 → 参数 / 材质
    ("SP2", "COMP_HAS_PROPERTY", "PR-MOTOR-PWR"),
    ("SP2", "COMP_HAS_PROPERTY", "PR-MOTOR-RPM"),
    ("SP3", "COMP_HAS_PROPERTY", "PR-SCREW-PITCH"),
    ("SP3", "COMP_HAS_PROPERTY", "PR-SCREW-GRADE"),
    ("SP4", "COMP_HAS_PROPERTY", "PR-RAIL-STRAIGHT"),
    ("SP4", "COMP_HAS_PROPERTY", "PR-RAIL-LOAD"),
    ("SP5", "COMP_HAS_PROPERTY", "PR-SERVO-TORQ"),
    ("SP-FIX", "COMP_HAS_PROPERTY", "PR-FIX-FORCE"),
    ("SP-FIX", "COMP_HAS_PROPERTY", "PR-FIX-POS"),
    ("SP-COOL", "COMP_HAS_PROPERTY", "PR-COOL-PRES"),
    ("BLADE", "COMP_HAS_PROPERTY", "PR-BLADE-PITCH"),
    ("LATHE-SP", "COMP_HAS_PROPERTY", "PR-LSP-PWR"),
    ("TL1", "COMP_HAS_PROPERTY", "PR-TL1-DIA"),
    ("SP1", "COMPONENT_MATERIAL", "MAT-BE"),  # 轴承材质
    ("TL1", "COMPONENT_MATERIAL", "MAT-TOOL"),  # 刀具材质
    ("BLADE", "COMPONENT_MATERIAL", "MAT-TOOL"),
    # 其他设备内部
    ("SAW", "HAS_COMPONENT", "BLADE"),
    ("C65", "HAS_COMPONENT", "LATHE-SP"),
    ("C65", "HAS_COMPONENT", "TOOLPOST"),
    # 原料 → 供应商 → 条款
    ("P1", "USES_MATERIAL", "RM1"),
    ("RM1", "SUPPLIED_MATERIAL", "SUP-B"),
    ("SP1", "SUPPLIED_BY", "SUP-A"),
    ("MAT-BE", "SUPPLIED_MATERIAL", "SUP-B"),
    ("SUP-A", "SUBJECT_TO", "CL-1"),
    ("SUP-B", "SUBJECT_TO", "CL-2"),
    # 业务层：供应商 → 合同 → 订单 → 客户/产品
    ("SUP-A", "HAS_CONTRACT", "CT-A"),
    ("SUP-B", "HAS_CONTRACT", "CT-B"),
    ("CT-A", "COVERS_ORDER", "ORD-1"),
    ("CT-B", "COVERS_ORDER", "ORD-2"),
    ("ORD-1", "PLACED_BY", "CUST-1"),
    ("ORD-2", "PLACED_BY", "CUST-1"),
    ("ORD-1", "ORDERS_PRODUCT", "P1"),
    ("ORD-2", "ORDERS_PRODUCT", "P1"),
    # 深挖：传感器测量参数
    ("SENSOR-RPM", "MEASURES", "PR-M1-RPM"),
    ("SENSOR-LOAD", "MEASURES", "PR-M1-FEED"),
    ("M1", "PROC_HAS_PROPERTY", "PR-M1-RPM-STD"),
    # 参数状态 → 症状（转速过高/过低 → 进给误差等）
    ("PR-M1-RPM", "PARAM_INDICATES", "SYM-RPM-HIGH"),
    ("PR-M1-RPM", "PARAM_INDICATES", "SYM-RPM-LOW"),
    ("SYM-RPM-HIGH", "CAUSES", "F-FEED-ERROR"),
    ("SYM-RPM-LOW", "CAUSES", "F-FEED-ERROR"),
    # 症状（设备/部件级）
    ("DMC-50H", "EQUIPMENT_HAS_SYMPTOM", "SYM-AIRCUT"),
    ("DMC-50H", "EQUIPMENT_HAS_SYMPTOM", "SYM-OVERLOAD"),
    ("SP1", "HAS_SYMPTOM", "SYM-NOISE"),
    ("SP3", "HAS_SYMPTOM", "SYM-VIBRATION"),
    # 因果：症状 → 候选故障
    ("SYM-AIRCUT", "CAUSES", "F-MAT-SHORT"),
    ("SYM-AIRCUT", "CAUSES", "F-CLAMP"),
    ("SYM-AIRCUT", "CAUSES", "F-TOOL"),
    ("SYM-OVERLOAD", "CAUSES", "F-CLAMP"),
    ("SYM-OVERLOAD", "CAUSES", "F-MAT-OVER"),
    ("SYM-VIBRATION", "CAUSES", "F-FEED-ERROR"),
    ("SYM-NOISE", "CAUSES", "F-BEARING-WEAR"),
    # 故障 → 缺陷
    ("F-MAT-SHORT", "AFFECTS", "D-SURFACE"),
    ("F-CLAMP", "AFFECTS", "D-SURFACE"),
    ("F-BEARING-WEAR", "AFFECTS", "D-SURFACE"),
    ("F-FEED-ERROR", "AFFECTS", "D-PARALLEL"),
    ("F-MAT-SHORT", "AFFECTS", "D-SIZE"),
    ("F-FEED-ERROR", "AFFECTS", "D-COAXIAL"),
]


# ---------------------------------------------------------------------------
# 深度本体生成（DMC-50H 五轴加工中心完整深挖）
# 数据：材料牌号(GB标准)、ISO 10816、SKF轴承、冷却/夹具/刀具为行业典型值（来源标注见 docs/research/demo-ontology-design.md）
# 结构：参数(标准/上限/下限→异常症状) → 症状(细分) → 故障(候选原因/证据) → 缺陷
# ---------------------------------------------------------------------------

# 参数: (id, name, value, unit, std, high_symptom, low_symptom)
_DEEP_PARAMS: list[tuple[str, str, str, str, str, str | None, str | None]] = [
    # 主轴系统
    ("PR-SPD-RPM", "主轴转速", "12000", "rpm", "12000±200", "SYM-RPM-HIGH", "SYM-RPM-LOW"),
    ("PR-SPD-PWR", "主轴功率", "20", "kW", "20", None, None),
    ("PR-SPD-TORQ", "主轴扭矩", "200", "Nm", "200", "SYM-OVERLOAD", None),
    ("PR-SPD-TAPER", "主轴锥度", "HSK-A63", "", "HSK-A63", None, None),
    ("PR-SPD-TEMP", "轴承温升", "45", "℃", "≤45", "SYM-OVERHEAT", None),
    ("PR-BEAR-MODEL", "轴承型号", "SKF-6205", "", "SKF 6205", None, None),
    ("PR-BEAR-LAYOUT", "轴承布置", "前3后2", "", "前3后2", None, None),
    ("PR-BEAR-PRELOAD", "轴承预紧", "轻预紧", "", "轻预紧", None, "SYM-NOISE"),
    ("PR-BEAR-GRADE", "轴承精度", "P4", "", "P4", None, None),
    ("PR-BEAR-LUBE", "润滑脂", "FAG-L252", "", "FAG L252", None, "SYM-NOISE"),
    ("PR-BEAR-SPEED", "极限转速", "12000", "rpm", "12000", "SYM-OVERHEAT", None),
    ("PR-LUBE-QTY", "润滑脂量", "3", "g", "3", None, "SYM-NOISE"),
    ("PR-LUBE-INT", "补脂周期", "3000", "h", "3000", None, None),
    # 冷却系统
    ("PR-COOL-TYPE", "冷却液", "乳化液", "", "乳化液", None, None),
    ("PR-COOL-CONC", "乳化液浓度", "5", "%", "3~8", None, None),
    ("PR-COOL-PRES", "冷却压力", "6", "bar", "4~8", None, "SYM-OVERHEAT"),
    ("PR-COOL-FLOW", "冷却流量", "20", "L/min", "15~30", None, "SYM-OVERHEAT"),
    ("PR-COOL-TEMP", "冷却液温度", "40", "℃", "≤40", "SYM-OVERHEAT", None),
    ("PR-COOL-FILTER", "过滤精度", "20", "μm", "20", None, None),
    # 进给系统
    ("PR-MOTOR-TORQ", "伺服扭矩", "12", "Nm", "12", "SYM-OVERLOAD", None),
    ("PR-MOTOR-RPM", "伺服转速", "3000", "rpm", "3000", None, None),
    ("PR-MOTOR-PWR", "伺服功率", "4", "kW", "4", None, None),
    ("PR-SCREW-PITCH", "丝杠导程", "12", "mm", "12", None, None),
    ("PR-SCREW-DIA", "丝杠直径", "32", "mm", "32", None, None),
    ("PR-SCREW-GRADE", "丝杠精度", "C3", "", "C3", None, None),
    ("PR-SCREW-PRELOAD", "丝杠预紧", "20", "%", "15~25", None, "SYM-BACKLASH"),
    ("PR-RAIL-STRAIGHT", "导轨直线度", "0.005", "mm", "0.005", None, "SYM-ACC-DROP"),
    ("PR-RAIL-LOAD", "导轨承载", "800", "kg", "800", "SYM-OVERLOAD", None),
    ("PR-RAIL-SLIDER", "滑块数", "4", "个", "4", None, None),
    ("PR-ENC-RES", "编码器分辨率", "0.001", "mm", "0.001", None, None),
    ("PR-ENC-ACC", "编码器精度", "5", "μm", "±5", None, "SYM-ACC-DROP"),
    ("PR-BACKLASH", "反向间隙", "0.005", "mm", "≤0.005", None, "SYM-BACKLASH"),
    # 刀具（面铣刀/立铣刀/钻头/镗刀/铰刀/丝锥）
    ("PR-TL1-MAT", "面铣刀材质", "YG6硬质合金", "", "YG6", None, "SYM-TL-WEAR"),
    ("PR-TL1-DIA", "面铣刀直径", "50", "mm", "50", None, None),
    ("PR-TL1-EDGES", "面铣刀刃数", "6", "刃", "6", None, None),
    ("PR-TL1-LIFE", "面铣刀寿命", "120", "min", "120", None, None),
    ("PR-TL2-MAT", "立铣刀材质", "涂层硬质合金", "", "TiAlN涂层", None, "SYM-TL-WEAR"),
    ("PR-TL2-DIA", "立铣刀直径", "16", "mm", "16", None, None),
    ("PR-TL2-EDGES", "立铣刀刃数", "4", "刃", "4", None, None),
    ("PR-TL3-MAT", "钻头材质", "高速钢", "", "HSS", None, "SYM-TL-WEAR"),
    ("PR-TL3-DIA", "钻头直径", "8", "mm", "8", None, None),
    ("PR-TL4-MAT", "镗刀材质", "硬质合金", "", "YG6", None, "SYM-TL-WEAR"),
    ("PR-TL5-MAT", "铰刀材质", "硬质合金", "", "YG6", None, "SYM-TL-WEAR"),
    ("PR-TL6-MAT", "丝锥材质", "高速钢", "", "HSS", None, "SYM-TL-WEAR"),
    # 夹具系统
    ("PR-FIX-HYD", "液压压力", "50", "bar", "50", None, "SYM-CLAMP-INS"),
    ("PR-FIX-FORCE", "夹持力", "20", "kN", "20", None, "SYM-CLAMP-INS"),
    ("PR-FIX-HOLD", "保压时间", "30", "s", "30", None, None),
    ("PR-FIX-POS", "定位精度", "0.01", "mm", "0.01", None, "SYM-ACC-DROP"),
    ("PR-CLAMP-FORCE", "夹紧力", "15", "kN", "15", None, "SYM-CLAMP-INS"),
    ("PR-CLAMP-STROKE", "夹紧行程", "10", "mm", "10", None, None),
    # 测量系统
    ("PR-SENS-RPM", "转速传感器", "0-20000", "rpm", "0-20000", None, None),
    ("PR-SENS-LOAD", "负载传感器", "0-100", "%", "0-100", None, None),
    ("PR-SENS-TEMP", "温度传感器", "0-150", "℃", "0-150", "SYM-OVERHEAT", None),
    ("PR-SENS-VIB", "振动传感器", "0-50", "mm/s", "0-50", "SYM-VIB-HF", None),
    ("PR-SENS-DISP", "位移传感器", "0-10", "mm", "0-10", None, "SYM-ACC-DROP"),
    ("PR-SENS-FORCE", "力传感器", "0-50", "kN", "0-50", None, None),
    ("PR-PROBE-ACC", "测头精度", "2", "μm", "±2", None, "SYM-ACC-DROP"),
    # 结构
    ("PR-BED-MAT", "床身材质", "HT300", "铸铁", "HT300", None, None),
    ("PR-BED-RIGID", "床身刚性", "500", "kN/μm", "500", None, "SYM-VIB-LF"),
    ("PR-BED-DAMP", "床身阻尼", "0.03", "", "0.03", None, "SYM-VIB-HF"),
]

# 组件: (id, name, parent, [param_ids], material_id, [symptom_ids], [fault_ids])
_DEEP_COMPS: list[tuple[str, str, str, list[str], str | None, list[str], list[str]]] = [
    ("SP-SPINDLE", "主轴系统", "DMC-50H", ["PR-SPD-RPM", "PR-SPD-PWR", "PR-SPD-TORQ", "PR-SPD-TAPER", "PR-SPD-TEMP"], None, [], []),
    ("SP1", "主轴轴承", "SP-SPINDLE", ["PR-BEAR-MODEL", "PR-BEAR-LAYOUT", "PR-BEAR-PRELOAD", "PR-BEAR-GRADE", "PR-BEAR-LUBE", "PR-BEAR-SPEED"], "MAT-BE", ["SYM-NOISE", "SYM-VIB-HF", "SYM-OVERHEAT"], ["F-BEARING-WEAR"]),
    ("SP-LUBE", "润滑系统", "SP-SPINDLE", ["PR-LUBE-QTY", "PR-LUBE-INT", "PR-BEAR-LUBE"], None, ["SYM-NOISE"], ["F-LUBE-INS"]),
    ("SP-COOL", "冷却系统", "DMC-50H", ["PR-COOL-TYPE", "PR-COOL-CONC", "PR-COOL-PRES", "PR-COOL-FLOW", "PR-COOL-TEMP", "PR-COOL-FILTER"], None, ["SYM-OVERHEAT"], ["F-COOL-INS"]),
    ("SP-FEED", "进给系统", "DMC-50H", [], None, [], []),
    ("SP5", "伺服电机", "SP-FEED", ["PR-MOTOR-TORQ", "PR-MOTOR-RPM", "PR-MOTOR-PWR"], None, ["SYM-OVERLOAD"], []),
    ("SP3", "滚珠丝杠", "SP-FEED", ["PR-SCREW-PITCH", "PR-SCREW-DIA", "PR-SCREW-GRADE", "PR-SCREW-PRELOAD"], None, ["SYM-BACKLASH", "SYM-VIB-LF"], ["F-SCREW-WEAR", "F-PRELOAD-FAIL"]),
    ("SP4", "直线导轨", "SP-FEED", ["PR-RAIL-STRAIGHT", "PR-RAIL-LOAD", "PR-RAIL-SLIDER"], None, ["SYM-ACC-DROP"], ["F-RAIL-WEAR"]),
    ("SP-ENC", "编码器", "SP-FEED", ["PR-ENC-RES", "PR-ENC-ACC", "PR-BACKLASH"], None, ["SYM-ACC-DROP", "SYM-BACKLASH"], ["F-SENSOR-DRIFT"]),
    ("SP-MAG", "刀库", "DMC-50H", [], None, [], []),
    ("TL1", "面铣刀", "SP-MAG", ["PR-TL1-MAT", "PR-TL1-DIA", "PR-TL1-EDGES", "PR-TL1-LIFE"], "MAT-TOOL", ["SYM-TL-WEAR"], ["F-TOOL-WEAR"]),
    ("TL2", "立铣刀", "SP-MAG", ["PR-TL2-MAT", "PR-TL2-DIA", "PR-TL2-EDGES"], "MAT-TOOL", ["SYM-TL-WEAR"], ["F-TOOL-WEAR"]),
    ("TL3", "钻头", "SP-MAG", ["PR-TL3-MAT", "PR-TL3-DIA"], "MAT-TOOL", ["SYM-TL-WEAR"], ["F-TOOL-WEAR"]),
    ("TL4", "镗刀", "SP-MAG", ["PR-TL4-MAT"], "MAT-TOOL", ["SYM-TL-WEAR"], ["F-TOOL-WEAR"]),
    ("TL5", "铰刀", "SP-MAG", ["PR-TL5-MAT"], "MAT-TOOL", ["SYM-TL-WEAR"], ["F-TOOL-WEAR"]),
    ("TL6", "丝锥", "SP-MAG", ["PR-TL6-MAT"], "MAT-TOOL", ["SYM-TL-WEAR"], ["F-TOOL-WEAR"]),
    ("SP-FIX", "夹具系统", "DMC-50H", ["PR-FIX-HYD", "PR-FIX-FORCE", "PR-FIX-HOLD", "PR-FIX-POS"], None, ["SYM-CLAMP-INS"], ["F-HYD-LEAK"]),
    ("SP-CLAMP", "夹紧元件", "SP-FIX", ["PR-CLAMP-FORCE", "PR-CLAMP-STROKE"], None, ["SYM-CLAMP-INS"], []),
    ("SP-MEAS", "测量系统", "DMC-50H", [], None, [], []),
    ("SENSOR-RPM", "转速传感器", "SP-MEAS", ["PR-SENS-RPM"], None, [], []),
    ("SENSOR-LOAD", "负载传感器", "SP-MEAS", ["PR-SENS-LOAD"], None, [], []),
    ("SENSOR-TEMP", "温度传感器", "SP-MEAS", ["PR-SENS-TEMP"], None, ["SYM-OVERHEAT"], ["F-SENSOR-DRIFT"]),
    ("SENSOR-VIB", "振动传感器", "SP-MEAS", ["PR-SENS-VIB"], None, ["SYM-VIB-HF"], []),
    ("SENSOR-DISP", "位移传感器", "SP-MEAS", ["PR-SENS-DISP"], None, ["SYM-ACC-DROP"], []),
    ("SENSOR-FORCE", "力传感器", "SP-MEAS", ["PR-SENS-FORCE"], None, [], []),
    ("PROBE", "测头", "SP-MEAS", ["PR-PROBE-ACC"], None, ["SYM-ACC-DROP"], []),
    ("BED", "床身", "DMC-50H", ["PR-BED-MAT", "PR-BED-RIGID", "PR-BED-DAMP"], None, ["SYM-VIB-HF", "SYM-VIB-LF"], []),
]

# ---- 扩展参数（主轴电机/皮带/密封/进给三轴/工作台/刀库/传感器/结构/工艺/标准/材料）----
_DEEP_PARAMS_2: list[tuple[str, str, str, str, str, str | None, str | None]] = [
    # 主轴电机/传动/密封
    ("PR-SPD-MOTOR-PWR", "主轴电机功率", "22", "kW", "22", None, None),
    ("PR-SPD-MOTOR-RPM", "电机额定转速", "8000", "rpm", "8000", None, None),
    ("PR-SPD-MOTOR-CURR", "电机电流", "45", "A", "45", "SYM-OVERLOAD", None),
    ("PR-SPD-MOTOR-TEMP", "电机温升", "60", "℃", "≤60", "SYM-OVERHEAT", None),
    ("PR-BELT-MODEL", "皮带型号", "5VX", "", "5VX", None, None),
    ("PR-BELT-TENSION", "皮带张紧力", "300", "N", "300", None, "SYM-BELT-SLIP"),
    ("PR-SEAL-TYPE", "主轴密封", "迷宫+唇形", "", "迷宫+唇形", None, None),
    ("PR-BEAR-ROLLER", "滚动体直径", "7.94", "mm", "7.94", None, None),
    ("PR-BEAR-CAGE", "保持架", "钢保持架", "", "钢保持架", None, None),
    ("PR-BEAR-CLEAR", "轴承游隙", "C3", "", "C3", "SYM-NOISE", None),
    # 进给三轴 / 工作台
    ("PR-FEED-X", "X轴行程", "800", "mm", "800", None, None),
    ("PR-FEED-Y", "Y轴行程", "600", "mm", "600", None, None),
    ("PR-FEED-Z", "Z轴行程", "600", "mm", "600", None, None),
    ("PR-FEED-RAPID", "快速进给", "30", "m/min", "30", None, None),
    ("PR-FEED-X-PITCH", "X丝杠导程", "12", "mm", "12", None, None),
    ("PR-FEED-Y-PITCH", "Y丝杠导程", "10", "mm", "10", None, None),
    ("PR-FEED-Z-PITCH", "Z丝杠导程", "12", "mm", "12", None, None),
    ("PR-TABLE-SIZE", "工作台尺寸", "700×650", "mm", "700×650", None, None),
    ("PR-TABLE-LOAD", "工作台承重", "500", "kg", "500", "SYM-OVERLOAD", None),
    ("PR-TABLE-TSLOT", "T型槽", "14×5", "mm", "14×5", None, None),
    # 刀库 / 刀柄
    ("PR-MAG-CAP", "刀库容量", "30", "把", "30", None, None),
    ("PR-MAG-TIME", "换刀时间", "3.5", "s", "3.5", None, "SYM-MAG-ERR"),
    ("PR-HOLDER-TAPER", "刀柄锥度", "HSK-A63", "", "HSK-A63", None, None),
    ("PR-HOLDER-BAL", "动平衡等级", "G2.5", "", "G2.5", None, "SYM-VIB-HF"),
    ("PR-HOLDER-PULL", "拉钉规格", "MAS-BT40", "", "MAS-BT40", None, "SYM-MAG-ERR"),
    # 测量更多传感器
    ("PR-SENS-PRES", "压力传感器", "0-100", "bar", "0-100", None, None),
    ("PR-SENS-ACCE", "加速度计", "0-50", "g", "0-50", "SYM-VIB-HF", None),
    # 结构
    ("PR-COLUMN-MAT", "立柱材质", "HT300", "铸铁", "HT300", None, None),
    ("PR-COLUMN-RIGID", "立柱刚性", "400", "kN/μm", "400", None, "SYM-VIB-LF"),
    ("PR-RAM-TRAVEL", "滑枕行程", "400", "mm", "400", None, None),
    # 工艺参数（每刀具切削参数）
    ("PR-PRC-FACE-RPM", "面铣转速", "2000", "rpm", "2000", "SYM-TL-WEAR", None),
    ("PR-PRC-FACE-FEED", "面铣进给", "600", "mm/min", "600", None, None),
    ("PR-PRC-FACE-DEPTH", "面铣切深", "2", "mm", "2", None, None),
    ("PR-PRC-END-RPM", "立铣转速", "4000", "rpm", "4000", "SYM-TL-WEAR", None),
    ("PR-PRC-END-FEED", "立铣进给", "800", "mm/min", "800", None, None),
    ("PR-PRC-DRILL-RPM", "钻孔转速", "3000", "rpm", "3000", None, None),
    ("PR-PRC-DRILL-FEED", "钻孔进给", "0.1", "mm/r", "0.1", None, None),
    ("PR-PRC-BORE-RPM", "镗孔转速", "1500", "rpm", "1500", None, None),
    ("PR-PRC-REAM-FEED", "铰孔进给", "0.2", "mm/r", "0.2", None, None),
    ("PR-PRC-TAP-RPM", "攻丝转速", "400", "rpm", "400", None, None),
    # 材料扩展（GB 标准）
    ("PR-6061-YIELD", "6061铝屈服强度", "276", "MPa", "276", None, None),
    ("PR-6061-TENSILE", "6061铝抗拉强度", "310", "MPa", "310", None, None),
    ("PR-6061-HARDNESS", "6061铝硬度", "95", "HB", "95", None, None),
    ("PR-6061-MODULUS", "6061铝弹性模量", "69", "GPa", "69", None, None),
    ("PR-HSS-HARDNESS", "高速钢硬度", "65", "HRC", "65", None, None),
    ("PR-HSS-REDHOT", "高速钢红硬性", "600", "℃", "600", None, None),
    ("PR-HT300-TENSILE", "HT300抗拉强度", "300", "MPa", "300", None, None),
    ("PR-HT300-HARDNESS", "HT300硬度", "230", "HB", "230", None, None),
    ("PR-HT300-DAMP", "HT300阻尼", "0.04", "", "0.04", None, None),
    # 标准（ISO 10816 振动分级 / ISO 230 精度）
    ("STD-ISO10816-A", "振动A区(优)", "<2.8", "mm/s", "<2.8", None, None),
    ("STD-ISO10816-B", "振动B区(良)", "2.8~7.1", "mm/s", "2.8~7.1", None, None),
    ("STD-ISO10816-C", "振动C区(注意)", "7.1~18", "mm/s", "7.1~18", "SYM-VIB-HF", None),
    ("STD-ISO10816-D", "振动D区(危险)", ">18", "mm/s", ">18", "SYM-VIB-HF", None),
    ("STD-ISO230-POS", "定位精度", "±0.01", "mm", "±0.01", None, "SYM-ACC-DROP"),
]

# ---- 扩展组件（主轴电机/皮带/三轴/工作台/刀库/结构/传感器）----
_DEEP_COMPS_2: list[tuple[str, str, str, list[str], str | None, list[str], list[str]]] = [
    ("SP2", "主轴电机", "SP-SPINDLE", ["PR-SPD-MOTOR-PWR", "PR-SPD-MOTOR-RPM", "PR-SPD-MOTOR-CURR", "PR-SPD-MOTOR-TEMP"], None, ["SYM-OVERLOAD", "SYM-OVERHEAT"], []),
    ("SP-BELT", "传动皮带", "SP-SPINDLE", ["PR-BELT-MODEL", "PR-BELT-TENSION"], None, ["SYM-BELT-SLIP"], ["F-BELT-SLIP"]),
    ("SP-SEAL", "主轴密封", "SP-SPINDLE", ["PR-SEAL-TYPE"], None, [], []),
    ("FEED-X", "X轴进给", "SP-FEED", ["PR-FEED-X", "PR-FEED-X-PITCH"], None, ["SYM-ACC-DROP"], ["F-SCREW-WEAR"]),
    ("FEED-Y", "Y轴进给", "SP-FEED", ["PR-FEED-Y", "PR-FEED-Y-PITCH"], None, ["SYM-ACC-DROP"], ["F-SCREW-WEAR"]),
    ("FEED-Z", "Z轴进给", "SP-FEED", ["PR-FEED-Z", "PR-FEED-Z-PITCH"], None, ["SYM-ACC-DROP"], ["F-SCREW-WEAR"]),
    ("TABLE", "工作台", "DMC-50H", ["PR-TABLE-SIZE", "PR-TABLE-LOAD", "PR-TABLE-TSLOT"], None, ["SYM-OVERLOAD"], []),
    ("MAG-DISC", "刀盘", "SP-MAG", ["PR-MAG-CAP"], None, [], []),
    ("MAG-ROBOT", "换刀机械手", "SP-MAG", ["PR-MAG-TIME"], None, ["SYM-MAG-ERR"], ["F-MAG-ERR"]),
    ("TOOL-HOLDER", "刀柄", "SP-MAG", ["PR-HOLDER-TAPER", "PR-HOLDER-BAL", "PR-HOLDER-PULL"], None, ["SYM-MAG-ERR", "SYM-VIB-HF"], ["F-MAG-ERR"]),
    ("SENSOR-PRES", "压力传感器", "SP-MEAS", ["PR-SENS-PRES"], None, [], []),
    ("SENSOR-ACCE", "加速度计", "SP-MEAS", ["PR-SENS-ACCE"], None, ["SYM-VIB-HF"], []),
    ("COLUMN", "立柱", "BED", ["PR-COLUMN-MAT", "PR-COLUMN-RIGID"], None, ["SYM-VIB-LF"], []),
    ("RAM", "滑枕", "BED", ["PR-RAM-TRAVEL"], None, [], []),
]

# ---- 材料（新：6061铝/高速钢/HT300铸铁，供 COMPONENT_MATERIAL 挂）----
_DEEP_MATS_2: list[tuple[str, str, dict]] = [
    ("Material", "MAT-6061", {"name": "6061 铝合金"}),
    ("Material", "MAT-HSS", {"name": "高速钢 W18Cr4V"}),
    ("Material", "MAT-HT300", {"name": "HT300 铸铁"}),
]

# ---- 扩展症状 ----
_DEEP_SYMPTOMS_2: list[tuple[str, str, str | None]] = [
    ("SYM-BELT-SLIP", "皮带打滑", None),
    ("SYM-MAG-ERR", "换刀异常", None),
]

# ---- 扩展故障 ----
_DEEP_FAULTS_2: list[tuple[str, str, list[str], str, list[str]]] = [
    ("F-BELT-SLIP", "皮带打滑", ["SYM-BELT-SLIP", "SYM-OVERLOAD"], "张紧力不足/皮带磨损", ["D-SURFACE"]),
    ("F-MAG-ERR", "换刀机构故障", ["SYM-MAG-ERR"], "机械手定位偏差/拉钉磨损", ["D-SIZE"]),
]


# ---- 扩展参数3（轴承零件级/进给三轴细分/冷却泵/夹具细分/材料更多）----
_DEEP_PARAMS_3: list[tuple[str, str, str, str, str, str | None, str | None]] = [
    # 主轴轴承零件级（内圈/外圈/滚动体/保持架）
    ("PR-BEAR-INNER-MAT", "内圈材质", "GCr15", "", "GCr15", None, None),
    ("PR-BEAR-INNER-HARD", "内圈硬度", "62", "HRC", "60~66", "SYM-NOISE", None),
    ("PR-BEAR-OUTER-MAT", "外圈材质", "GCr15", "", "GCr15", None, None),
    ("PR-BEAR-BALL-NUM", "滚动体数量", "12", "粒", "12", None, "SYM-NOISE"),
    ("PR-BEAR-BALL-DIA", "滚动体直径", "7.94", "mm", "7.94", None, None),
    ("PR-BEAR-CAGE-MAT", "保持架材质", "钢板", "", "钢板", None, None),
    ("PR-BEAR-RACEWAY", "滚道粗糙度", "0.1", "μm", "≤0.1", None, "SYM-NOISE"),
    # 进给三轴细分（丝杠/导轨/电机）
    ("PR-XSCREW-PITCH", "X丝杠导程", "12", "mm", "12", None, None),
    ("PR-XSCREW-PRELOAD", "X丝杠预紧", "20", "%", "15~25", None, "SYM-BACKLASH"),
    ("PR-XRAIL-STRAIGHT", "X导轨直线度", "0.005", "mm", "0.005", None, "SYM-ACC-DROP"),
    ("PR-YSCREW-PITCH", "Y丝杠导程", "10", "mm", "10", None, None),
    ("PR-YSCREW-PRELOAD", "Y丝杠预紧", "20", "%", "15~25", None, "SYM-BACKLASH"),
    ("PR-YRAIL-STRAIGHT", "Y导轨直线度", "0.005", "mm", "0.005", None, "SYM-ACC-DROP"),
    ("PR-ZSCREW-PITCH", "Z丝杠导程", "12", "mm", "12", None, None),
    ("PR-ZSCREW-PRELOAD", "Z丝杠预紧", "20", "%", "15~25", None, "SYM-BACKLASH"),
    ("PR-ZRAIL-STRAIGHT", "Z导轨直线度", "0.005", "mm", "0.005", None, "SYM-ACC-DROP"),
    ("PR-XMOTOR-TORQ", "X电机扭矩", "12", "Nm", "12", "SYM-OVERLOAD", None),
    ("PR-YMOTOR-TORQ", "Y电机扭矩", "10", "Nm", "10", "SYM-OVERLOAD", None),
    ("PR-ZMOTOR-TORQ", "Z电机扭矩", "15", "Nm", "15", "SYM-OVERLOAD", None),
    # 冷却泵 / 过滤 / 喷嘴
    ("PR-PUMP-PWR", "冷却泵功率", "3", "kW", "3", None, None),
    ("PR-PUMP-FLOW", "冷却泵流量", "25", "L/min", "25", None, "SYM-OVERHEAT"),
    ("PR-FILTER-ACC", "过滤器精度", "20", "μm", "20", None, None),
    ("PR-FILTER-CLOG", "滤芯堵塞度", "30", "%", "≤30", None, "SYM-OVERHEAT"),
    ("PR-NOZZLE-NUM", "喷嘴数量", "4", "个", "4", None, None),
    ("PR-NOZZLE-ANGLE", "喷嘴角度", "30", "°", "30", None, None),
    # 夹具细分
    ("PR-VBLOCK-ANGLE", "V型块角度", "90", "°", "90", None, "SYM-CLAMP-INS"),
    ("PR-VBLOCK-ACC", "V型块精度", "0.005", "mm", "0.005", None, "SYM-ACC-DROP"),
    ("PR-PIN-DIA", "定位销直径", "12", "mm", "12", None, "SYM-CLAMP-INS"),
    ("PR-PIN-ACC", "定位销精度", "0.002", "mm", "0.002", None, "SYM-ACC-DROP"),
    ("PR-CYL-DIA", "液压缸缸径", "80", "mm", "80", None, None),
    ("PR-CYL-STROKE", "液压缸行程", "25", "mm", "25", None, None),
    ("PR-CYL-LEAK", "液压缸泄漏量", "0.5", "mL/min", "≤0.5", None, "SYM-CLAMP-INS"),
    # 材料更多参数（45# 热处理 / GCr15 热处理 / 硬质合金更多）
    ("PR-CB-QUENCH", "45#钢淬透深度", "5", "mm", "≥5", None, None),
    ("PR-CB-NORMALIZE", "45#钢正火硬度", "197", "HB", "≤197", None, None),
    ("PR-CB-ELONG", "45#钢延伸率", "16", "%", "≥16", None, None),
    ("PR-CB-IMPACT", "45#钢冲击韧性", "39", "J", "≥39", None, None),
    ("PR-BE-ANNEAL", "GCr15退火硬度", "210", "HB", "≤210", None, None),
    ("PR-BE-QUENCH", "GCr15淬火温度", "840", "℃", "830~860", None, None),
    ("PR-BE-TEMP", "GCr15回火温度", "160", "℃", "150~170", None, None),
    ("PR-TOOL-BEND", "硬质合金抗弯", "1900", "MPa", "1900", None, "SYM-TL-WEAR"),
    ("PR-TOOL-FRACTURE", "硬质合金断裂韧性", "13", "MPa·m½", "13", None, "SYM-TL-WEAR"),
    ("PR-TOOL-COATING", "刀具涂层", "TiAlN", "", "TiAlN", None, None),
    # 传感器更多
    ("PR-SENS-CURR", "电流传感器", "0-60", "A", "0-60", "SYM-OVERLOAD", None),
    ("PR-SENS-TEMP-RES", "测温分辨率", "0.1", "℃", "0.1", None, None),
]

# ---- 扩展组件3（轴承零件/三轴丝杠导轨电机/冷却泵/夹具细分）----
_DEEP_COMPS_3: list[tuple[str, str, str, list[str], str | None, list[str], list[str]]] = [
    ("BEAR-INNER", "轴承内圈", "SP1", ["PR-BEAR-INNER-MAT", "PR-BEAR-INNER-HARD"], "MAT-BE", ["SYM-NOISE"], ["F-BEARING-WEAR"]),
    ("BEAR-OUTER", "轴承外圈", "SP1", ["PR-BEAR-OUTER-MAT", "PR-BEAR-RACEWAY"], "MAT-BE", ["SYM-NOISE"], ["F-BEARING-WEAR"]),
    ("BEAR-BALL", "滚动体", "SP1", ["PR-BEAR-BALL-NUM", "PR-BEAR-BALL-DIA", "PR-BEAR-INNER-HARD"], "MAT-BE", ["SYM-NOISE"], ["F-BEARING-WEAR"]),
    ("BEAR-CAGE", "保持架", "SP1", ["PR-BEAR-CAGE-MAT"], None, [], []),
    ("X-SCREW", "X轴丝杠", "FEED-X", ["PR-XSCREW-PITCH", "PR-XSCREW-PRELOAD"], None, ["SYM-BACKLASH"], ["F-SCREW-WEAR", "F-PRELOAD-FAIL"]),
    ("X-RAIL", "X轴导轨", "FEED-X", ["PR-XRAIL-STRAIGHT"], None, ["SYM-ACC-DROP"], ["F-RAIL-WEAR"]),
    ("X-MOTOR", "X轴电机", "FEED-X", ["PR-XMOTOR-TORQ"], None, ["SYM-OVERLOAD"], []),
    ("Y-SCREW", "Y轴丝杠", "FEED-Y", ["PR-YSCREW-PITCH", "PR-YSCREW-PRELOAD"], None, ["SYM-BACKLASH"], ["F-SCREW-WEAR", "F-PRELOAD-FAIL"]),
    ("Y-RAIL", "Y轴导轨", "FEED-Y", ["PR-YRAIL-STRAIGHT"], None, ["SYM-ACC-DROP"], ["F-RAIL-WEAR"]),
    ("Y-MOTOR", "Y轴电机", "FEED-Y", ["PR-YMOTOR-TORQ"], None, ["SYM-OVERLOAD"], []),
    ("Z-SCREW", "Z轴丝杠", "FEED-Z", ["PR-ZSCREW-PITCH", "PR-ZSCREW-PRELOAD"], None, ["SYM-BACKLASH"], ["F-SCREW-WEAR", "F-PRELOAD-FAIL"]),
    ("Z-RAIL", "Z轴导轨", "FEED-Z", ["PR-ZRAIL-STRAIGHT"], None, ["SYM-ACC-DROP"], ["F-RAIL-WEAR"]),
    ("Z-MOTOR", "Z轴电机", "FEED-Z", ["PR-ZMOTOR-TORQ"], None, ["SYM-OVERLOAD"], []),
    ("COOL-PUMP", "冷却泵", "SP-COOL", ["PR-PUMP-PWR", "PR-PUMP-FLOW"], None, ["SYM-OVERHEAT"], ["F-COOL-INS"]),
    ("COOL-FILTER", "过滤器", "SP-COOL", ["PR-FILTER-ACC", "PR-FILTER-CLOG"], None, ["SYM-OVERHEAT"], ["F-COOL-INS"]),
    ("COOL-NOZZLE", "冷却喷嘴", "SP-COOL", ["PR-NOZZLE-NUM", "PR-NOZZLE-ANGLE"], None, [], []),
    ("FIX-VBLOCK", "V型块", "SP-FIX", ["PR-VBLOCK-ANGLE", "PR-VBLOCK-ACC"], None, ["SYM-CLAMP-INS", "SYM-ACC-DROP"], []),
    ("FIX-PIN", "定位销", "SP-FIX", ["PR-PIN-DIA", "PR-PIN-ACC"], None, ["SYM-CLAMP-INS", "SYM-ACC-DROP"], []),
    ("FIX-CYL", "液压缸", "SP-FIX", ["PR-CYL-DIA", "PR-CYL-STROKE", "PR-CYL-LEAK"], None, ["SYM-CLAMP-INS"], ["F-HYD-LEAK"]),
    ("SENSOR-CURR", "电流传感器", "SP-MEAS", ["PR-SENS-CURR"], None, ["SYM-OVERLOAD"], []),
]


# ---- 扩展参数4（刀具寿命/工艺/更多材料/缺陷参数）----
_DEEP_PARAMS_4: list[tuple[str, str, str, str, str, str | None, str | None]] = [
    ("PR-TL2-LIFE", "立铣刀寿命", "150", "min", "150", None, "SYM-TL-WEAR"),
    ("PR-TL3-LIFE", "钻头寿命", "200", "min", "200", None, "SYM-TL-WEAR"),
    ("PR-TL4-LIFE", "镗刀寿命", "100", "min", "100", None, "SYM-TL-WEAR"),
    ("PR-TL5-LIFE", "铰刀寿命", "180", "min", "180", None, "SYM-TL-WEAR"),
    ("PR-TL6-LIFE", "丝锥寿命", "80", "min", "80", None, "SYM-TL-WEAR"),
    ("PR-TL1-COAT", "面铣刀涂层", "TiAlN", "", "TiAlN", None, "SYM-TL-WEAR"),
    ("PR-PRC-END-DEPTH", "立铣切深", "1.5", "mm", "1.5", None, None),
    ("PR-PRC-DRILL-DEPTH", "钻孔深度", "15", "mm", "15", None, None),
    ("PR-PRC-BORE-FEED", "镗孔进给", "0.15", "mm/r", "0.15", None, None),
    ("PR-PRC-REAM-RPM", "铰孔转速", "1200", "rpm", "1200", None, None),
    ("PR-PRC-TAP-FEED", "攻丝进给", "0.5", "mm/r", "0.5", None, None),
    ("PR-PRC-FACE-COOL", "面铣冷却", "开", "", "开", None, "SYM-OVERHEAT"),
    # 更多材料（304不锈钢/钨钢/40Cr更多）
    ("PR-304-YIELD", "304钢屈服强度", "205", "MPa", "205", None, None),
    ("PR-304-TENSILE", "304钢抗拉强度", "520", "MPa", "520", None, None),
    ("PR-304-HARDNESS", "304钢硬度", "187", "HB", "187", None, None),
    ("PR-304-ELONG", "304钢延伸率", "40", "%", "≥40", None, None),
    ("PR-TUNG-HARDNESS", "钨钢硬度", "92", "HRA", "92", None, None),
    ("PR-TUNG-DENSITY", "钨钢密度", "14.5", "g/cm³", "14.5", None, None),
    ("PR-CB-HEATTREAT", "45#热处理", "正火", "", "正火/调质", None, None),
    ("PR-CB-YIELD-STD", "45#屈服标准", "≥355", "MPa", "≥355", None, None),
    ("PR-PR-QUENCH-TEMP", "40Cr淬火温度", "850", "℃", "840~860", None, None),
    ("PR-PR-TEMP", "40Cr回火温度", "550", "℃", "520~560", None, None),
    ("PR-BE-SURFACE", "GCr15表面粗糙度", "0.2", "μm", "≤0.2", None, "SYM-NOISE"),
    # 缺陷相关参数
    ("PR-SURFACE-RA", "表面粗糙度Ra", "1.6", "μm", "≤1.6", "SYM-SURFACE-BAD", None),
    ("PR-PARALLEL-TOL", "平行度公差", "0.1", "mm", "0.1", None, "SYM-ACC-DROP"),
    ("PR-COAXIAL-TOL", "同轴度公差", "0.05", "mm", "0.05", None, "SYM-ACC-DROP"),
    ("PR-ROUNDNESS-TOL", "圆度公差", "0.02", "mm", "0.02", None, "SYM-ACC-DROP"),
    ("PR-POSITION-TOL", "位置度公差", "0.05", "mm", "0.05", None, "SYM-ACC-DROP"),
    # 更多传感器量程
    ("PR-SENS-VIB-FREQ", "振动频响", "10-1000", "Hz", "10-1000", "SYM-VIB-HF", None),
    ("PR-SENS-TEMP-ACC", "测温精度", "0.5", "℃", "±0.5", None, None),
    ("PR-SENS-DISP-RES", "位移分辨率", "0.1", "μm", "0.1", None, None),
]

# ---- 扩展参数5（设备级/工艺/传感器/材料/ISO9001）----
_DEEP_PARAMS_5: list[tuple[str, str, str, str, str, str | None, str | None]] = [
    ("PR-MACHINE-WEIGHT", "整机重量", "8000", "kg", "8000", None, None),
    ("PR-MACHINE-PWR", "整机额定功率", "30", "kW", "30", "SYM-OVERLOAD", None),
    ("PR-MACHINE-VOLT", "供电电压", "380", "V", "380", None, None),
    ("PR-MACHINE-PNEU", "气源压力", "6", "bar", "6", None, "SYM-CLAMP-INS"),
    ("PR-ACCEL-X", "X轴加速度", "5", "m/s²", "5", None, None),
    ("PR-ACCEL-Z", "Z轴加速度", "8", "m/s²", "8", None, None),
    ("PR-SPD-ACCEL", "主轴加速时间", "2", "s", "2", None, None),
    ("PR-SPD-DECEL", "主轴减速时间", "1.5", "s", "1.5", None, None),
    ("PR-PRC-DWELL", "暂停时间", "0.5", "s", "0.5", None, None),
    ("PR-PRC-CUT-PATH", "走刀路径", "往复", "", "往复", None, None),
    ("PR-PRC-FINISH-ALLOW", "精加工余量", "0.3", "mm", "0.3", None, None),
    ("PR-SENS-TEMP-RESP", "测温响应", "1", "s", "1", None, None),
    ("PR-SENS-VIB-BW", "振动带宽", "10k", "Hz", "10k", None, None),
    ("PR-65MN-YIELD", "65Mn屈服强度", "785", "MPa", "785", None, None),
    ("PR-65MN-TENSILE", "65Mn抗拉强度", "980", "MPa", "980", None, None),
    ("PR-65MN-HARDNESS", "65Mn硬度", "40", "HRC", "40", None, None),
    ("PR-CAGE-STEEL", "保持架材料", "08F", "", "08F", None, None),
    ("PR-ISO9001-SCOPE", "ISO9001范围", "质量管理体系", "", "质量管理体系", None, None),
    ("PR-ISO9001-QC", "ISO9001检验", "首件/巡检/终检", "", "首件/巡检/终检", None, None),
    ("PR-ISO9001-NCR", "ISO9001不合格品", "隔离/评审/处置", "", "隔离/评审/处置", None, None),
    ("PR-SENS-FORCE-RES", "力传感器分辨率", "0.1", "N", "0.1", None, None),
    ("PR-SENS-DISP-RANGE", "位移传感器量程", "10", "mm", "10", None, None),
    ("PR-CLAMP-WEAR", "夹紧元件磨损量", "0.05", "mm", "≤0.05", None, "SYM-CLAMP-INS"),
    ("PR-BEAR-LIFE", "轴承额定寿命", "20000", "h", "20000", None, "SYM-NOISE"),
]

# ---- 扩展参数6（材料更多/标准更多/设备细节）----
_DEEP_PARAMS_6: list[tuple[str, str, str, str, str, str | None, str | None]] = [
    ("PR-PR-QUENCH-ABILITY", "40Cr淬透性", "J10=28", "", "J10≥28", None, None),
    ("PR-PR-TEMP-HARD", "40Cr调质硬度", "28", "HRC", "28~32", None, None),
    ("PR-BE-FATIGUE-LIMIT", "GCr15疲劳极限", "480", "MPa", "480", None, None),
    ("PR-BE-COMPRESS", "GCr15抗压强度", "2100", "MPa", "2100", None, None),
    ("PR-TOOL-DENSITY", "硬质合金密度", "14.8", "g/cm³", "14.8", None, None),
    ("PR-TOOL-THERMAL", "硬质合金导热", "80", "W/mK", "80", None, "SYM-TL-WEAR"),
    ("PR-6061-ELONG", "6061铝延伸率", "12", "%", "≥12", None, None),
    ("PR-6061-FATIGUE", "6061铝疲劳强度", "96", "MPa", "96", None, None),
    ("PR-ISO230-REPEAT", "重复定位精度", "±0.005", "mm", "±0.005", None, "SYM-ACC-DROP"),
    ("PR-ISO230-BACKLASH", "ISO230反向间隙", "0.003", "mm", "≤0.003", None, "SYM-BACKLASH"),
    ("PR-ISO230-STRAIGHT", "ISO230直线度", "0.01", "mm", "≤0.01", None, "SYM-ACC-DROP"),
    ("PR-ISO9001-REVIEW", "ISO9001管理评审", "年度", "", "年度", None, None),
    ("PR-ISO9001-AUDIT", "ISO9001内审", "年度", "", "年度", None, None),
    ("PR-ISO9001-TRAIN", "ISO9001培训", "上岗/年度", "", "上岗/年度", None, None),
    ("PR-SPINDLE-CENTER", "主轴中心高", "250", "mm", "250", None, None),
    ("PR-SPINDLE-NOSE", "主轴鼻端", "HSK-A63", "", "HSK-A63", None, None),
    ("PR-COOL-TANK", "冷却水箱容积", "120", "L", "120", None, None),
    ("PR-COOL-CHILLER", "冷却制冷功率", "2", "kW", "2", None, "SYM-OVERHEAT"),
    ("PR-LUBE-PUMP", "润滑泵流量", "0.2", "L/min", "0.2", None, "SYM-NOISE"),
    ("PR-LUBE-PRES", "润滑压力", "2", "bar", "2", None, "SYM-NOISE"),
    ("PR-AIR-PRES", "压缩空气压力", "6", "bar", "6", None, "SYM-CLAMP-INS"),
    ("PR-MAG-WEIGHT", "刀库承载", "200", "kg", "200", None, None),
    ("PR-CHIP-CONVEY", "排屑器类型", "刮板式", "", "刮板式", None, None),
    ("PR-CHIP-VOLUME", "排屑能力", "0.5", "m³/h", "0.5", None, None),
    ("PR-SAFETY-DOOR", "安全门联锁", "有", "", "有", None, None),
    ("PR-SAFETY-STOP", "急停响应", "0.1", "s", "0.1", None, None),
    ("PR-OPERATOR-UI", "操作界面", "SIEMENS 840D", "", "SIEMENS 840D", None, None),
    ("PR-CNC-RES", "CNC分辨率", "0.001", "mm", "0.001", None, None),
    ("PR-SERVO-LOOP", "伺服环增益", "20", "Hz", "20", None, "SYM-VIB-LF"),
    ("PR-SPINDLE-DIRECT", "主轴直驱", "是", "", "是", None, None),
]

# ---- 挂载修复（把孤立参数挂到材料/工序/传感器/轴承零件/设备）----
_DEEP_MAT_MOUNT: dict[str, list[str]] = {
    "MAT-CB": ["PR-CB-QUENCH", "PR-CB-NORMALIZE", "PR-CB-ELONG", "PR-CB-IMPACT", "PR-CB-HEATTREAT", "PR-CB-YIELD-STD"],
    "MAT-PR": ["PR-PR-QUENCH-TEMP", "PR-PR-TEMP", "PR-PR-QUENCH-ABILITY", "PR-PR-TEMP-HARD"],
    "MAT-BE": ["PR-BE-ANNEAL", "PR-BE-QUENCH", "PR-BE-TEMP", "PR-BE-SURFACE", "PR-BE-FATIGUE-LIMIT", "PR-BE-COMPRESS"],
    "MAT-TOOL": ["PR-TOOL-COATING", "PR-TOOL-BEND", "PR-TOOL-FRACTURE", "PR-TOOL-DENSITY", "PR-TOOL-THERMAL"],
}
_DEEP_PROC_MOUNT: dict[str, list[str]] = {
    "M1": ["PR-PRC-END-DEPTH", "PR-PRC-DRILL-DEPTH", "PR-PRC-BORE-FEED", "PR-PRC-REAM-RPM", "PR-PRC-TAP-FEED",
           "PR-PRC-DWELL", "PR-PRC-CUT-PATH", "PR-PRC-FINISH-ALLOW", "PR-PRC-FACE-COOL"],
}
_DEEP_SENSOR_MOUNT: dict[str, list[str]] = {
    "SENSOR-TEMP": ["PR-SENS-TEMP-RESP", "PR-SENS-TEMP-ACC"],
    "SENSOR-VIB": ["PR-SENS-VIB-BW", "PR-SENS-VIB-FREQ"],
    "SENSOR-DISP": ["PR-SENS-DISP-RES", "PR-SENS-DISP-RANGE"],
    "SENSOR-FORCE": ["PR-SENS-FORCE-RES"],
}
_DEEP_COMP_MOUNT: dict[str, list[str]] = {
    "BEAR-BALL": ["PR-BEAR-ROLLER"],
    "BEAR-CAGE": ["PR-BEAR-CAGE"],
}
_DEEP_EQUIP_MOUNT: list[str] = [
    "PR-MACHINE-WEIGHT", "PR-MACHINE-PWR", "PR-MACHINE-VOLT", "PR-MACHINE-PNEU",
    "PR-SPINDLE-CENTER", "PR-SPINDLE-NOSE", "PR-COOL-TANK", "PR-COOL-CHILLER",
    "PR-LUBE-PUMP", "PR-LUBE-PRES", "PR-AIR-PRES", "PR-MAG-WEIGHT",
    "PR-CHIP-CONVEY", "PR-CHIP-VOLUME", "PR-SAFETY-DOOR", "PR-SAFETY-STOP",
    "PR-OPERATOR-UI", "PR-CNC-RES", "PR-SERVO-LOOP", "PR-SPINDLE-DIRECT",
    "PR-ACCEL-X", "PR-ACCEL-Z", "PR-SPD-ACCEL", "PR-SPD-DECEL",
]

# ---- 横向网状关系（参数关联 / 部件驱动 / 工序用部件 / 故障级联）----
_DEEP_LINKS: dict[str, list[tuple[str, str]]] = {
    "PARAM_AFFECTS": [
        ("PR-SPD-RPM", "PR-SPD-TEMP"), ("PR-COOL-PRES", "PR-SPD-TEMP"), ("PR-COOL-FLOW", "PR-SPD-TEMP"),
        ("PR-SCREW-PRELOAD", "PR-BACKLASH"), ("PR-FIX-FORCE", "PR-FIX-POS"),
        ("PR-RAIL-LOAD", "PR-RAIL-STRAIGHT"), ("PR-TOOL-WEAR", "PR-SURFACE-RA"),
        ("PR-LUBE-QTY", "PR-BEAR-LUBE"), ("PR-BEAR-PRELOAD", "PR-SPD-TEMP"),
        ("PR-PUMP-FLOW", "PR-COOL-FLOW"), ("PR-CYL-LEAK", "PR-FIX-FORCE"),
        ("PR-CLAMP-FORCE", "PR-FIX-FORCE"), ("PR-RAIL-STRAIGHT", "PR-FIX-POS"),
        ("PR-BACKLASH", "PR-ENC-ACC"), ("PR-MOTOR-TORQ", "PR-SCREW-PITCH"),
        ("PR-SPD-RPM", "PR-PRC-FACE-RPM"), ("PR-SCREW-PRELOAD", "PR-FEED-RAPID"),
    ],
    "PART_DRIVES": [
        ("SP2", "SP-SPINDLE"), ("SP5", "SP3"), ("SP3", "TABLE"), ("SP-BELT", "SP-SPINDLE"),
        ("X-MOTOR", "X-SCREW"), ("Y-MOTOR", "Y-SCREW"), ("Z-MOTOR", "Z-SCREW"),
        ("SP1", "SP-SPINDLE"),
    ],
    "PROCESS_USES": [
        ("M1", "TL1"), ("M1", "TL2"), ("M1", "TL3"), ("M1", "TL4"), ("M1", "TL5"), ("M1", "TL6"),
        ("M1", "SP-COOL"), ("M1", "SP-FIX"), ("M1", "SP-MEAS"),
    ],
    "FAULT_CAUSES": [
        ("F-LUBE-INS", "F-BEARING-WEAR"), ("F-COOL-INS", "F-BEARING-WEAR"),
        ("F-PRELOAD-FAIL", "F-SCREW-WEAR"), ("F-BEARING-WEAR", "F-SCREW-WEAR"),
        ("F-SENSOR-DRIFT", "F-SCREW-WEAR"),
    ],
}

# ---- 扩展缺陷 / 材料 ----
_DEEP_DEFECTS_2: list[tuple[str, str]] = [
    ("D-SHAPE", "形状误差"),
    ("D-POSITION", "位置度超差"),
    ("D-ROUNDNESS", "圆度超差"),
]
_DEEP_MATS_3: list[tuple[str, str, dict]] = [
    ("Material", "MAT-304", {"name": "304 不锈钢"}),
    ("Material", "MAT-TUNG", {"name": "钨钢"}),
]
_DEEP_SYMPTOMS_3: list[tuple[str, str, str | None]] = [
    ("SYM-SURFACE-BAD", "表面质量差", None),
]


# 额外症状: (id, name, 上层症状id)
_DEEP_SYMPTOMS: list[tuple[str, str, str | None]] = [
    ("SYM-RPM-HIGH", "转速过高", None),
    ("SYM-RPM-LOW", "转速过低", None),
    ("SYM-OVERHEAT", "温升过高", None),
    ("SYM-BACKLASH", "反向间隙过大", None),
    ("SYM-ACC-DROP", "精度下降", None),
    ("SYM-CLAMP-INS", "夹持力不足", None),
    ("SYM-TL-WEAR", "刀具磨损", None),
    ("SYM-NOISE-SQUEAL", "尖啸异响", "SYM-NOISE"),
    ("SYM-NOISE-CLICK", "咔哒异响", "SYM-NOISE"),
    ("SYM-NOISE-RUMBLE", "隆隆异响", "SYM-NOISE"),
    ("SYM-VIB-HF", "高频振动", "SYM-VIBRATION"),
    ("SYM-VIB-LF", "低频振动", "SYM-VIBRATION"),
]

# 额外故障: (id, name, [原因症状], 证据说明, [缺陷])
_DEEP_FAULTS: list[tuple[str, str, list[str], str, list[str]]] = [
    ("F-BEARING-WEAR", "轴承磨损", ["SYM-NOISE", "SYM-VIB-HF", "SYM-OVERHEAT"], "异响/高频振动/温升超标", ["D-SURFACE", "D-COAXIAL"]),
    ("F-LUBE-INS", "润滑不足", ["SYM-NOISE", "SYM-OVERHEAT"], "润滑脂量不足/补脂周期超期", ["D-SURFACE"]),
    ("F-COOL-INS", "冷却不足", ["SYM-OVERHEAT"], "冷却压力/流量不足或液温过高", ["D-SURFACE", "D-SIZE"]),
    ("F-SCREW-WEAR", "丝杠磨损", ["SYM-VIB-LF", "SYM-BACKLASH"], "进给精度下降/反向间隙增大", ["D-PARALLEL", "D-SIZE"]),
    ("F-PRELOAD-FAIL", "预紧失效", ["SYM-BACKLASH"], "丝杠预紧力衰减", ["D-SIZE"]),
    ("F-RAIL-WEAR", "导轨磨损", ["SYM-ACC-DROP", "SYM-VIB-LF"], "导轨直线度超差", ["D-PARALLEL", "D-SIZE"]),
    ("F-TOOL-WEAR", "刀具磨损", ["SYM-TL-WEAR"], "刀具寿命耗尽/切削参数不当", ["D-SURFACE", "D-SIZE"]),
    ("F-HYD-LEAK", "液压泄漏", ["SYM-CLAMP-INS"], "液压压力下降/夹持力不足", ["D-SIZE"]),
    ("F-SENSOR-DRIFT", "传感器漂移", ["SYM-ACC-DROP"], "传感器零点漂移/精度超差", ["D-SIZE", "D-COAXIAL"]),
]


def _deep_ontology() -> tuple[list, list]:
    """生成深度本体的节点与边（DMC-50H 系统/部件/参数/症状/故障深挖）。"""
    nodes: list = []
    edges: list = []
    params_all = _DEEP_PARAMS + _DEEP_PARAMS_2 + _DEEP_PARAMS_3 + _DEEP_PARAMS_4 + _DEEP_PARAMS_5 + _DEEP_PARAMS_6
    comps_all = _DEEP_COMPS + _DEEP_COMPS_2 + _DEEP_COMPS_3
    syms_all = _DEEP_SYMPTOMS + _DEEP_SYMPTOMS_2 + _DEEP_SYMPTOMS_3
    faults_all = _DEEP_FAULTS + _DEEP_FAULTS_2
    # 参数节点
    for pid, name, value, unit, _std, _h, _l in params_all:
        nodes.append(("Property", pid, {"name": name, "value": value, "unit": unit}))
    # 组件节点 + 父子（设备→子系统用 HAS_COMPONENT，部件级嵌套用 COMPONENT_HAS_COMPONENT）+ 参数 + 材质
    comp_ids = {c[0] for c in comps_all}
    for cid, name, parent, params, mat, _syms, _faults in comps_all:
        nodes.append(("Component", cid, {"name": name}))
        rel = "COMPONENT_HAS_COMPONENT" if parent in comp_ids else "HAS_COMPONENT"
        edges.append((parent, rel, cid))
        for p in params:
            edges.append((cid, "COMP_HAS_PROPERTY", p))
        if mat:
            edges.append((cid, "COMPONENT_MATERIAL", mat))
    # 扩展材料节点 + 材料参数归属（MAT_HAS_PROPERTY）
    for label, mid, props in _DEEP_MATS_2 + _DEEP_MATS_3:
        nodes.append((label, mid, props))
    mat_param_map = {
        "MAT-6061": ["PR-6061-YIELD", "PR-6061-TENSILE", "PR-6061-HARDNESS", "PR-6061-MODULUS"],
        "MAT-HSS": ["PR-HSS-HARDNESS", "PR-HSS-REDHOT"],
        "MAT-HT300": ["PR-HT300-TENSILE", "PR-HT300-HARDNESS", "PR-HT300-DAMP"],
        "MAT-304": ["PR-304-YIELD", "PR-304-TENSILE", "PR-304-HARDNESS", "PR-304-ELONG"],
        "MAT-TUNG": ["PR-TUNG-HARDNESS", "PR-TUNG-DENSITY"],
    }
    # 缺陷节点（扩展：形状/位置度/圆度）
    for did, dname in _DEEP_DEFECTS_2:
        nodes.append(("Defect", did, {"name": dname}))
    for mid, pids in mat_param_map.items():
        for p in pids:
            edges.append((mid, "MAT_HAS_PROPERTY", p))
    # 工艺参数挂到工序（PROC_HAS_PROPERTY）
    proc_param_map = {
        "M1": ["PR-PRC-FACE-RPM", "PR-PRC-FACE-FEED", "PR-PRC-FACE-DEPTH", "PR-PRC-END-RPM", "PR-PRC-END-FEED",
               "PR-PRC-DRILL-RPM", "PR-PRC-DRILL-FEED", "PR-PRC-BORE-RPM", "PR-PRC-REAM-FEED", "PR-PRC-TAP-RPM"],
    }
    for proc, pids in proc_param_map.items():
        for p in pids:
            edges.append((proc, "PROC_HAS_PROPERTY", p))
    # 标准参数挂到 DMC-50H 设备（ISO 10816 / ISO 230 标准）
    for pid, _nm, _v, _u, _std, _h, _l in params_all:
        if pid.startswith("STD-"):
            edges.append(("DMC-50H", "EQUIPMENT_HAS_STANDARD", pid))
    # 症状节点
    for sid, name, _parent in syms_all:
        nodes.append(("Symptom", sid, {"name": name}))
    # 组件 → 症状
    for cid, _name, _p, _par, _m, syms, _faults in comps_all:
        for s in syms:
            edges.append((cid, "HAS_SYMPTOM", s))
    # 参数 → 症状（PARAM_INDICATES）
    for pid, _n, _v, _u, _std, high, low in params_all:
        if high:
            edges.append((pid, "PARAM_INDICATES", high))
        if low:
            edges.append((pid, "PARAM_INDICATES", low))
    # 故障节点 + 症状→故障 + 故障→缺陷
    for fid, name, cause_syms, _ev, defects in faults_all:
        nodes.append(("Fault", fid, {"name": name}))
        for s in cause_syms:
            edges.append((s, "CAUSES", fid))
        for d in defects:
            edges.append((fid, "AFFECTS", d))
    # 挂载修复：材料/工艺/传感器/轴承零件参数（消孤立）
    for mid, pids in _DEEP_MAT_MOUNT.items():
        for p in pids:
            edges.append((mid, "MAT_HAS_PROPERTY", p))
    for proc, pids in _DEEP_PROC_MOUNT.items():
        for p in pids:
            edges.append((proc, "PROC_HAS_PROPERTY", p))
    for comp, pids in _DEEP_SENSOR_MOUNT.items():
        for p in pids:
            edges.append((comp, "COMP_HAS_PROPERTY", p))
    for comp, pids in _DEEP_COMP_MOUNT.items():
        for p in pids:
            edges.append((comp, "COMP_HAS_PROPERTY", p))
    for pid in _DEEP_EQUIP_MOUNT:
        edges.append(("DMC-50H", "EQUIPMENT_HAS_PARAM", pid))
    # 补挂剩余孤立：ISO9001 标准→设备、材料补参、症状细分→故障、缺陷→故障、传感器/保持架参数
    for pid in ["PR-ISO9001-SCOPE", "PR-ISO9001-QC", "PR-ISO9001-NCR", "PR-ISO9001-REVIEW", "PR-ISO9001-AUDIT", "PR-ISO9001-TRAIN"]:
        edges.append(("DMC-50H", "EQUIPMENT_HAS_STANDARD", pid))
    nodes.append(("Material", "MAT-65MN", {"name": "65Mn 弹簧钢"}))
    for p in ["PR-65MN-YIELD", "PR-65MN-TENSILE", "PR-65MN-HARDNESS"]:
        edges.append(("MAT-65MN", "MAT_HAS_PROPERTY", p))
    for p in ["PR-6061-ELONG", "PR-6061-FATIGUE"]:
        edges.append(("MAT-6061", "MAT_HAS_PROPERTY", p))
    edges.append(("SENSOR-TEMP", "COMP_HAS_PROPERTY", "PR-SENS-TEMP-RES"))
    edges.append(("BEAR-CAGE", "COMP_HAS_PROPERTY", "PR-CAGE-STEEL"))
    # 症状细分（尖啸/咔哒/隆隆）→ 轴承磨损故障
    for s in ["SYM-NOISE-SQUEAL", "SYM-NOISE-CLICK", "SYM-NOISE-RUMBLE"]:
        edges.append((s, "CAUSES", "F-BEARING-WEAR"))
    # 修复孤立小簇：活塞杆/装配链连主图、材料挂实际用途
    edges.append(("P2", "USES_MATERIAL", "RM1"))  # 活塞杆也用钢棒（RM1 在主图）
    edges.append(("P3", "HAS_PART", "P1"))  # 组装气缸含气缸底
    edges.append(("P3", "HAS_PART", "P2"))  # 组装气缸含活塞杆
    edges.append(("BED", "COMPONENT_MATERIAL", "MAT-HT300"))  # 床身铸铁
    edges.append(("TL6", "COMPONENT_MATERIAL", "MAT-HSS"))  # 丝锥高速钢
    edges.append(("TL1", "COMPONENT_MATERIAL", "MAT-TUNG"))  # 面铣刀钨钢可选
    edges.append(("P1", "HAS_MATERIAL", "MAT-6061"))  # 气缸底可选铝合金
    edges.append(("P2", "HAS_MATERIAL", "MAT-304"))  # 活塞杆可选不锈钢
    edges.append(("SP-FIX", "COMPONENT_MATERIAL", "MAT-65MN"))  # 夹具弹簧钢
    # 缺陷 → 对应故障
    edges.append(("F-RAIL-WEAR", "AFFECTS", "D-ROUNDNESS"))
    edges.append(("F-FEED-ERROR", "AFFECTS", "D-POSITION"))
    edges.append(("F-SCREW-WEAR", "AFFECTS", "D-SHAPE"))
    # 装配链（P3 组装气缸 → 装配工序 → 装配站）
    nodes.append(("Product", "P3", {"name": "组装气缸 cylinder-assembly"}))
    edges.append(("P3", "HAS_PROCESS", "A1"))
    edges.append(("A1", "AT_EQUIPMENT", "ASSY"))
    # 横向网状关系：参数关联 / 部件驱动 / 工序用部件 / 故障级联
    for rel, links in _DEEP_LINKS.items():
        for src, dst in links:
            edges.append((src, rel, dst))
    return nodes, edges


def _merged_ontology() -> tuple[list, list]:
    """合并基础 + 深度本体，按 id / (src,rel,dst) 去重（基础优先保留判定属性）。"""
    deep_nodes, deep_edges = _deep_ontology()
    seen_n: set[str] = set()
    nodes = []
    for label, nid, props in NODE_SPECS + deep_nodes:
        if nid in seen_n:
            continue
        seen_n.add(nid)
        nodes.append((label, nid, props))
    seen_e: set[tuple[str, str, str]] = set()
    edges = []
    for src, rel, dst in EDGE_SPECS + deep_edges:
        key = (src, rel, dst)
        if key in seen_e:
            continue
        seen_e.add(key)
        edges.append((src, rel, dst))
    return nodes, edges


def build_graph(path: str = ":memory:") -> LadybugGraphStore:
    """建真实知识图谱（工艺图 + 深度本体 + 因果 + 供应链），幂等。"""
    all_nodes, all_edges = _merged_ontology()
    graph = LadybugGraphStore(path, demo_schema())
    for label, nid, props in all_nodes:
        cols = ", ".join(f"{k}: ${k}" for k in props)
        graph.execute(f"CREATE (n:{label} {{id: $id, {cols}}})", {"id": nid, **props})
    for src, rel, dst in all_edges:
        graph.execute(
            f"MATCH (a {{id:$src}}), (b {{id:$dst}}) CREATE (a)-[:{rel}]->(b)",
            {"src": src, "dst": dst},
        )
    return graph


def export_ontology() -> dict:
    """导出本体图（节点 + 边）——供前端 d3-force 可视化（全景 / 推理点亮）。"""
    all_nodes, all_edges = _merged_ontology()
    return {
        "nodes": [{"id": nid, "label": label, **props} for label, nid, props in all_nodes],
        "edges": [{"source": src, "rel": rel, "target": dst} for src, rel, dst in all_edges],
    }


def set_equipment_signal(graph: LadybugGraphStore, signal_stats, anomalous: bool, symptom: str) -> None:
    """把真实工艺信号写进 DMC-50H 节点（ABox 个体观测入图）。"""
    graph.execute(
        "MATCH (e:Equipment {id:'DMC-50H'}) "
        "SET e.face_milling_curr_mean = $c, e.face_milling_load_mean = $l, "
        "e.face_milling_curr_peak = $p, e.face_milling_anomalous = $a, e.symptom = $s",
        {"c": signal_stats.curr6_mean, "l": signal_stats.load6_mean,
         "p": signal_stats.curr6_peak, "a": anomalous, "s": symptom},
    )


def set_material_weight(graph: LadybugGraphStore, weight: float, below: bool) -> None:
    """把真实来料重量写进 RM1 节点。"""
    graph.execute(
        "MATCH (m:Material {id:'RM1'}) SET m.weight = $w, m.weight_below_baseline = $b",
        {"w": weight, "b": below},
    )


if __name__ == "__main__":
    print_knowledge_tree()
