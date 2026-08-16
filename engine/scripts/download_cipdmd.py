"""CiP-DMD 数据下载器：气缸底铣削样本的 frontside 工艺信号 + 子工序时间戳。

下载对象（cylinder_bottom / cnc_milling_machine / DMC-50H 铣床）：
- 异常样本全量：anomaly=1（来料短 98）+ anomaly=2（夹持 39）+ anomaly=3（杂项 11）
- 正常样本：前 N 个有 frontside 信号的
每样本下载 frontside_internal_machine_signals.h5（PLC 工艺参数）+ frontside_timestamp_process_pairs.csv。

用法：python scripts/download_cipdmd.py [数据目录] [正常样本数]
默认数据目录 /tmp/cipdmd，正常样本数 30。幂等（已存在跳过）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "https://cloud.ptw-darmstadt.de/remote.php/dav/public-files/5Wv34VRZEXBLsZK"
DATA_DIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/cipdmd"
NORMAL_N = int(sys.argv[2]) if len(sys.argv) > 2 else 30


def main() -> None:
    meta_path = os.path.join(DATA_DIR, "meta_data.json")
    with open(meta_path) as f:
        data = json.load(f)

    # 选样本：异常全量 + 正常前 N
    by_anom: dict[str, list[tuple[str, str, str]]] = {}
    for p in data:
        for pd in p.get("process_data", []):
            if pd["name"] != "cnc_milling_machine":
                continue
            internal = next(
                (dp for dp in pd.get("data_paths", []) if dp.endswith("frontside_internal_machine_signals.h5")), None
            )
            csvp = next(
                (dp for dp in pd.get("data_paths", []) if dp.endswith("frontside_timestamp_process_pairs.csv")), None
            )
            if internal and csvp:
                by_anom.setdefault(str(pd["anomaly"]), []).append((p["part_id"], internal, csvp))
    pick = (
        by_anom.get("1", [])[:]
        + by_anom.get("2", [])[:]
        + by_anom.get("3", [])[:]
        + by_anom.get("0", [])[:NORMAL_N]
    )
    print(f"选样: 异常1={len(by_anom.get('1',[]))} 异常2={len(by_anom.get('2',[]))} "
          f"异常3={len(by_anom.get('3',[]))} 正常={min(NORMAL_N, len(by_anom.get('0',[])))} 共{len(pick)}")

    # manifest + 下载任务
    os.makedirs(os.path.join(DATA_DIR, "signals"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "csv"), exist_ok=True)
    anom_map = {}
    for p in data:
        for pd in p.get("process_data", []):
            if pd["name"] == "cnc_milling_machine":
                anom_map[p["part_id"]] = str(pd["anomaly"])
    tasks: list[tuple[str, str]] = []
    with open(os.path.join(DATA_DIR, "manifest.tsv"), "w") as mf:
        for pid, internal, csvp in pick:
            a = anom_map[pid]
            folder = os.path.basename(os.path.dirname(internal))
            mf.write(f"{pid}\t{a}\t{internal}\t{csvp}\n")
            tasks.append((f"{BASE}/{internal}", f"{DATA_DIR}/signals/{pid}_{a}_{folder}_frontside_internal_machine_signals.h5"))
            tasks.append((f"{BASE}/{csvp}", f"{DATA_DIR}/csv/{pid}_{a}_{folder}_frontside_timestamp_process_pairs.csv"))
    print(f"待下载 {len(tasks)} 个文件")

    def fetch(item: tuple[str, str]) -> str:
        url, dst = item
        if os.path.exists(dst) and os.path.getsize(dst) > 10000:
            return "skip"
        r = subprocess.run(["curl", "-s", "--max-time", "300", "-o", dst, url])
        return "ok" if r.returncode == 0 else "fail"

    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(fetch, tasks))
    from collections import Counter

    print("结果:", Counter(results))
    print("signals:", len(os.listdir(os.path.join(DATA_DIR, "signals"))),
          "csv:", len(os.listdir(os.path.join(DATA_DIR, "csv"))))


if __name__ == "__main__":
    main()
