"""审计底座：依据链 + 哈希链（ARD §5.2，选型 D7 SQLite）。

职责边界（防膨胀）：横切只读，不改变推理结果，只记录结论与依据。
每条结论 = 原始证据引用 + 标准条款 + 链式哈希。
篡改任一环节（输入或任一层结论）→ verify 失败——白箱可审计落到工程实现。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict

from ..contracts import EvidenceEvent, TraceStep


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


class SQLiteAudit:
    """链式哈希审计：H(输入) → H(层1) → H(层2) → ... → 溯源根指纹，可独立重算。"""

    def __init__(self, path: str = ":memory:"):
        # check_same_thread=False：服务层可能跨线程调用（FastAPI/TestClient）
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chain (
                idx      INTEGER PRIMARY KEY,
                layer    TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                step_hash TEXT NOT NULL,
                content   TEXT NOT NULL
            )
            """
        )
        self._conn.commit()
        self._trigger_hash = ""

    # ---- 链构建 ----

    def begin(self, trigger: EvidenceEvent) -> None:
        """新事故：重算输入指纹，清空旧链。输入被篡改 → 根指纹对不上。"""
        payload = json.dumps(asdict(trigger), sort_keys=True, default=str)
        self._trigger_hash = _sha256(payload.encode("utf-8"))
        self._conn.execute("DELETE FROM chain")
        self._conn.commit()

    def append(self, step: TraceStep) -> str:
        """追加一层结论，返回该步哈希。"""
        prev = self._trigger_hash if self._last_hash() == "" else self._last_hash()
        content = json.dumps(asdict(step), sort_keys=True, default=str)
        step_hash = _sha256((prev + content).encode("utf-8"))
        self._conn.execute(
            "INSERT INTO chain (idx, layer, prev_hash, step_hash, content) VALUES (?,?,?,?,?)",
            (self._count(), step.layer, prev, step_hash, content),
        )
        self._conn.commit()
        return step_hash

    # ---- 校验 ----

    def root(self) -> str:
        return self._last_hash()

    def verify(self, root_hash: str) -> bool:
        """独立重算全链：H(trigger) → 逐层 H(prev + content)，比对根指纹。"""
        if self._trigger_hash == "":
            return False
        cur = self._trigger_hash
        rows = self._conn.execute("SELECT prev_hash, content FROM chain ORDER BY idx").fetchall()
        for r in rows:
            if r["prev_hash"] != cur:
                return False  # 链接断开 = 中间环节被篡改
            cur = _sha256((cur + r["content"]).encode("utf-8"))
        return cur == root_hash

    # ---- 内部 ----

    def _last_hash(self) -> str:
        row = self._conn.execute("SELECT step_hash FROM chain ORDER BY idx DESC LIMIT 1").fetchone()
        return row["step_hash"] if row else ""

    def _count(self) -> int:
        return self._conn.execute("SELECT count(*) AS c FROM chain").fetchone()["c"]

    def close(self) -> None:
        self._conn.close()
