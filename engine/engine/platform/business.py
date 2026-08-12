"""业务层：SQLite 实现（ARD D7 + §6.2 BusinessStore）。

职责边界（防膨胀）：台账/批次/工单/合同的事实与状态存储查询，不做推理、不接数据源。
Record 是通用 dict（key = 字段名）；一楼以内存库 + 通用过滤支撑模拟事实测试，
二楼在契约内填真实业务 schema（换业务数据，不换引擎）。
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from ..contracts import Action, ActionResult


class SQLiteBusinessStore:
    """轻量通用业务库：type + JSON payload 的扁平表（单文件或内存）。"""

    def __init__(self, path: str = ":memory:"):
        # check_same_thread=False：服务层可能跨线程调用（FastAPI/TestClient）
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                key       TEXT PRIMARY KEY,
                type      TEXT NOT NULL,
                payload   TEXT NOT NULL,      -- JSON
                updated_ts REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS actions (
                id          TEXT PRIMARY KEY,
                action_type TEXT NOT NULL,
                target_ref  TEXT NOT NULL,
                description TEXT NOT NULL,
                approved    INTEGER NOT NULL DEFAULT 0,
                result      TEXT,
                ts          REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    # ---- 业务事实查询 ----

    def query(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """按 type + 字段过滤查询记录。Record 为通用 dict，字段在 payload 里。"""
        f = dict(filters)  # 不污染调用方的 filters
        type_ = f.pop("type", None)
        sql = "SELECT key, type, payload FROM records"
        params: list[Any] = []
        if type_ is not None:
            sql += " WHERE type = ?"
            params.append(type_)
        rows = self._conn.execute(sql, params).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            payload = json.loads(r["payload"])
            rec = {"key": r["key"], "type": r["type"], **payload}
            if all(rec.get(k) == v for k, v in f.items()):
                out.append(rec)
        return out

    def upsert(self, key: str, type_: str, payload: dict[str, Any]) -> None:
        """写/改一条业务事实（知识入库与执行层共用）。"""
        self._conn.execute(
            "INSERT OR REPLACE INTO records (key, type, payload, updated_ts) VALUES (?,?,?,?)",
            (key, type_, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        self._conn.commit()

    # ---- 动作落库 ----

    def apply(self, actions: list[Action]) -> list[ActionResult]:
        """执行层落库：记录动作及执行结果。"""
        results: list[ActionResult] = []
        for a in actions:
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO actions "
                    "(id, action_type, target_ref, description, approved, result, ts) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        a.id,
                        a.action_type,
                        a.target_ref,
                        a.description,
                        int(a.approved),
                        a.result,
                        time.time(),
                    ),
                )
                self._conn.commit()
                results.append(ActionResult(a.id, True, "recorded"))
            except sqlite3.Error as e:
                results.append(ActionResult(a.id, False, str(e)))
        return results

    def close(self) -> None:
        self._conn.close()
