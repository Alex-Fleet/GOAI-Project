"""ABox 数据加载器：从 CiP-DMD 真实数据加载具体零件实例。

每个零件 = 个体断言（ABox）：
- 端面铣削工艺信号特征（从 internal_machine_signals.h5 + timestamp pairs 计算）
- 质检测量（surface_roughness 等）
- 锯切来料重量（meta_data.json 的 saw quality）

demo 服务用此模块把真实样本喂给归因器与推理链。
"""

from __future__ import annotations

import csv
import glob
import json
import os

import h5py

from .attribution import SignalStats

DATA_DIR = os.environ.get("CIPDMD_DATA", "/tmp/cipdmd")


class SampleLoader:
    """样本数据加载器（ABox）。"""

    def __init__(self, data_dir: str = DATA_DIR):
        self._dir = data_dir
        self._meta = self._load_meta()
        self._qc = self._load_qc()

    def _load_meta(self) -> dict:
        path = os.path.join(self._dir, "meta_data.json")
        with open(path) as f:
            return json.load(f)

    def _load_qc(self) -> dict[str, dict]:
        qc = {}
        path = os.path.join(self._dir, "quality_data.csv")
        with open(path) as f:
            for r in csv.DictReader(f, delimiter=";"):
                qc[r["part_id"]] = r
        return qc

    # ---- 查询 ----

    def sample_ids(self, anomaly: str | None = None) -> list[str]:
        """列出样本 part_id（可按官方 anomaly 过滤）。"""
        out = []
        for p in self._meta:
            for pd in p.get("process_data", []):
                if pd["name"] == "cnc_milling_machine" and (anomaly is None or str(pd["anomaly"]) == anomaly):
                    out.append(p["part_id"])
        return out

    def official_anomaly(self, part_id: str) -> str | None:
        for p in self._meta:
            if p["part_id"] != part_id:
                continue
            for pd in p.get("process_data", []):
                if pd["name"] == "cnc_milling_machine":
                    return str(pd["anomaly"])
        return None

    def quality(self, part_id: str) -> dict:
        return self._qc.get(part_id, {})

    def saw_weight(self, part_id: str) -> float | None:
        """锯切来料重量（该零件的毛坯测量）。"""
        for p in self._meta:
            if p["part_id"] != part_id:
                continue
            for q in p.get("quality_data", []):
                if q["process"] == "saw":
                    for m in q.get("measurements", []):
                        if m["feature"] == "weight":
                            return float(m["value"])
        return None

    def signal_stats(self, part_id: str, anomaly: str | None = None) -> SignalStats | None:
        """从 h5 计算端面铣削信号统计（face_milling 子工序）。"""
        sig = glob.glob(os.path.join(self._dir, "signals", f"{part_id}_*frontside_internal_machine_signals.h5"))
        pairs = glob.glob(os.path.join(self._dir, "csv", f"{part_id}_*frontside_timestamp_process_pairs.csv"))
        if not sig or not pairs:
            return None
        try:
            with h5py.File(sig[0], "r") as hf:
                cols = list(hf["data"].attrs["column_names"])
                arr = hf["data"][:]
        except OSError:  # 下载截断/损坏 → 无信号数据（不崩溃）
            return None
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
            curr = arr[mask, cols.index("aaCurr6")]
            load = arr[mask, cols.index("aaLoad6")]
            return SignalStats(
                curr6_mean=float(curr.mean()),
                load6_mean=float(load.mean()),
                curr6_peak=float(curr.max()),
            )
        return None

    def full_sample(self, part_id: str) -> dict:
        """一个零件的完整 ABox 数据（demo 事故输入）。"""
        anom = self.official_anomaly(part_id)
        return {
            "part_id": part_id,
            "official_anomaly": anom,
            "quality": self.quality(part_id),
            "saw_weight": self.saw_weight(part_id),
            "signal": self.signal_stats(part_id, anom),
        }

    def pick_demo_samples(self) -> list[dict]:
        """挑 demo 三事故样本：来料短（异常1 空切）+ 夹持（异常2 过载）+ 杂项（异常3）。"""
        out = []
        # 异常1：空切典型（SR 高 + 信号极低）
        for pid in self.sample_ids("1"):
            s = self.full_sample(pid)
            if s["signal"] and s["signal"].curr6_mean < 1.0 and float(s["quality"].get("surface_roughness", 0) or 0) > 3:
                out.append(s)
                break
        # 异常2：过载典型
        for pid in self.sample_ids("2"):
            s = self.full_sample(pid)
            if s["signal"] and s["signal"].curr6_mean > 2.8 and float(s["quality"].get("surface_roughness", 0) or 0) > 2.4:
                out.append(s)
                break
        # 异常3：杂项
        for pid in self.sample_ids("3"):
            s = self.full_sample(pid)
            if s["signal"] and s["quality"]:
                out.append(s)
                break
        return out
