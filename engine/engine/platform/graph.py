"""知识层：Ladybug 属性图实现（选型 D1，ARD §5.1 / §6.2 GraphStore）。

职责边界（防膨胀）：只做属性图的存储与 Cypher 遍历查询——不接数据源、不写业务数据、
不参与推理判定。推理核只通过 GraphStore 契约消费图数据，不感知 Ladybug。

Ladybug 工程约束（spike 结论）：
- Database 路径是「文件」（如 mydb.lbug），不是目录；
- 无显式事务（begin/commit/rollback 已移除）→ 原子性靠「单条 execute 内多语句」；
- 强 schema：节点/关系必须先建表（CREATE ... TABLE IF NOT EXISTS 幂等）；
- 关系表不存在时查询抛 Binder exception → query 返回空列表（知识不完整不崩溃）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import ladybug

from ..contracts import EdgeRef, NodeRef

# ---------------------------------------------------------------------------
# Schema 定义（一楼通用 5 域，ARD §5.1；二楼在契约内扩展，不修改 engine/）
# ---------------------------------------------------------------------------


@dataclass
class NodeTypeDef:
    label: str
    props: dict[str, str] = field(default_factory=dict)  # 属性名 -> Ladybug 类型
    pk: str = "id"


@dataclass
class RelTypeDef:
    label: str
    src: str
    dst: str


@dataclass
class SchemaDef:
    nodes: list[NodeTypeDef] = field(default_factory=list)
    rels: list[RelTypeDef] = field(default_factory=list)


def default_schema() -> SchemaDef:
    """一楼通用 5 域 schema——制造行业通用抽象，非业务特化。

    工艺图 / 对象构造 / 故障因果 / 供应链 / 条款：任何工厂都具备的概念。
    二楼按行业重灌内容（换知识），不换类型结构；如确有新概念再泛化（ARD §6.3）。
    """
    nodes = [
        NodeTypeDef("Product", {"id": "STRING", "name": "STRING"}),
        NodeTypeDef("Process", {"id": "STRING", "name": "STRING"}),
        NodeTypeDef("Equipment", {"id": "STRING", "model": "STRING"}),
        NodeTypeDef("Material", {"id": "STRING", "name": "STRING"}),
        NodeTypeDef("Component", {"id": "STRING", "name": "STRING"}),
        NodeTypeDef("Supplier", {"id": "STRING", "name": "STRING"}),
        NodeTypeDef("Batch", {"id": "STRING", "name": "STRING"}),
        NodeTypeDef("Symptom", {"id": "STRING", "name": "STRING"}),
        NodeTypeDef("Fault", {"id": "STRING", "name": "STRING"}),
        NodeTypeDef("Defect", {"id": "STRING", "name": "STRING"}),
        NodeTypeDef("Clause", {"id": "STRING", "name": "STRING"}),
    ]
    rels = [
        RelTypeDef("HAS_PROCESS", "Product", "Process"),
        RelTypeDef("AT_EQUIPMENT", "Process", "Equipment"),
        RelTypeDef("USES_MATERIAL", "Product", "Material"),
        RelTypeDef("HAS_COMPONENT", "Equipment", "Component"),
        RelTypeDef("HAS_SYMPTOM", "Component", "Symptom"),
        RelTypeDef("CAUSES", "Symptom", "Fault"),
        RelTypeDef("AFFECTS", "Fault", "Defect"),
        RelTypeDef("SUPPLIED_BY", "Component", "Supplier"),
        RelTypeDef("SUPPLIED_MATERIAL", "Material", "Supplier"),
        RelTypeDef("BATCH_OF", "Component", "Batch"),
        RelTypeDef("MATERIAL_BATCH", "Material", "Batch"),
        RelTypeDef("SUBJECT_TO", "Supplier", "Clause"),
    ]
    return SchemaDef(nodes, rels)


# ---------------------------------------------------------------------------
# Ladybug 实现
# ---------------------------------------------------------------------------


class LadybugGraphStore:
    """GraphStore 的 Ladybug 实现（嵌入式属性图，单文件持久化）。"""

    def __init__(self, path: str, schema: SchemaDef | None = None):
        self._db = ladybug.Database(path)
        self._conn = ladybug.Connection(self._db)
        if schema is not None:
            self.init_schema(schema)

    # ---- schema 管理 ----

    def init_schema(self, schema: SchemaDef) -> None:
        for node in schema.nodes:
            self._create_node_table(node)
        for rel in schema.rels:
            self._create_rel_table(rel)

    def _create_node_table(self, node: NodeTypeDef) -> None:
        cols = ", ".join(f"{k} {v}" for k, v in node.props.items())
        stmt = f"CREATE NODE TABLE IF NOT EXISTS {node.label}({cols}, PRIMARY KEY({node.pk}))"
        self._conn.execute(stmt)

    def _create_rel_table(self, rel: RelTypeDef) -> None:
        stmt = f"CREATE REL TABLE IF NOT EXISTS {rel.label}(FROM {rel.src} TO {rel.dst})"
        try:
            self._conn.execute(stmt)
        except RuntimeError as e:  # Ladybug 无 REL TABLE IF NOT EXISTS 时的兜底
            if "already exists" not in str(e):
                raise

    # ---- 查询（GraphStore 契约）----

    def query(self, start: NodeRef, rel: str, direction: str = "forward") -> list[EdgeRef]:
        """沿 rel 边从 start 出发，forward 出边 / backward 入边，返回边轨迹。

        Ladybug 强 schema：需显式绑定 s 的类型（start.label），否则 t.* 无法解析属性。
        """
        if direction == "forward":
            cypher = (
                f"MATCH (s:{start.label})-[r:{rel}]->(t) WHERE s.id = $id "
                f"RETURN label(t) AS lbl, t.id AS tid, t.*"
            )
        elif direction == "backward":
            cypher = (
                f"MATCH (s:{start.label})<-[r:{rel}]-(t) WHERE s.id = $id "
                f"RETURN label(t) AS lbl, t.id AS tid, t.*"
            )
        else:
            raise ValueError(f"direction must be 'forward'|'backward', got {direction!r}")
        try:
            res = self._conn.execute(cypher, {"id": start.id})
        except RuntimeError as e:
            if "does not exist" in str(e):  # 关系表未建 → 知识不完整，返回空而非崩溃
                return []
            raise
        return self._rows_to_edges(start, rel, res, backward=(direction == "backward"))

    def get_node(self, ref: NodeRef) -> NodeRef | None:
        cypher = f"MATCH (n:{ref.label}) WHERE n.id = $id RETURN label(n) AS lbl, n.id AS tid, n.*"
        res = self._conn.execute(cypher, {"id": ref.id})
        rows = res.get_all()
        if not rows:
            return None
        return self._row_to_node(rows[0], res.get_column_names())

    def load_scope(self, scope: str) -> None:
        # 按需加载是知识层策略（ARD P5）；Ladybug 单文件已全量加载，接口占位。
        pass

    def execute(self, cypher: str, params: dict[str, Any] | None = None) -> Any:
        """执行任意 Cypher——知识入库（D6）/ 测试灌数据入口。

        推理路径只走 query/get_node（GraphStore 契约）；本方法供数据管理使用，
        不进入契约（二楼知识入库工具与测试专用）。
        """
        return self._conn.execute(cypher, params or {})

    # ---- 内部：结果解析 ----

    def _rows_to_edges(self, src: NodeRef, rel: str, res: Any, backward: bool = False) -> list[EdgeRef]:
        names = res.get_column_names()
        if not backward:
            return [EdgeRef(src, rel, self._row_to_node(row, names)) for row in res.get_all()]
        # backward 查询：MATCH (s:..)<-[r]-(t)，从 src 出发找入边，真实图方向是 t -> src。
        # 边轨迹必须还原为真实方向（可回放），故 EdgeRef(t, rel, src)。
        return [EdgeRef(self._row_to_node(row, names), rel, src) for row in res.get_all()]

    def _row_to_node(self, row: list, names: list[str]) -> NodeRef:
        # 列名 = ['lbl', 'tid', '<label>.id', '<label>.prop2', ...]，主键已由 tid 提供
        lbl, tid = row[0], row[1]
        props: dict[str, Any] = {}
        for name, value in zip(names[2:], row[2:], strict=True):
            key = name.split(".", 1)[-1]  # 去掉 '<label>.' 前缀
            if key == "id":
                continue
            props[key] = value
        return NodeRef(lbl, tid, props)

    def close(self) -> None:
        self._conn.close()
        self._db.close()
