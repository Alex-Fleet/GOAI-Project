# GOAI-Project

工业质量事故跨层溯源与责任定位 Agent（GOAI 世界人工智能开源大赛参赛项目）。

**神经-符号架构（AI proposes, Logic disposes）**：LLM 三职责（NLU 解析 / 探索提议 / 人话表达）+ 确定性推理核沿属性图把关——每步结论有真实证据、可回放、哈希链审计。

## Demo 演示（气动缸实例）

浏览器打开前端工作台（后端 8800 + 前端 5173）：

```bash
# 后端（真实工艺信号 + 神经-符号推理 + 归因）
cd engine
DEEPSEEK_API_KEY=<你的key> python -m demo.serve_demo   # 默认 8800

# 前端
cd engine/frontend && npm run dev                        # 默认 5173
```

演示流程：丢进一批 CiP-DMD 气缸底零件（真实工艺信号）→ 系统批量归因 → 推理后出现「正常 / 来料尺寸不足 / 工件夹持不平 / 无法归因」几个问题 → 点击展开推理路径、责任方、违约金、哈希链。

## 演示数据（CiP-DMD）

- **来源**：TU Darmstadt ptW 公开数据集 CiP-DMD（Cylinder in Process Data Mining Dataset），ownCloud 公开分享。
- **范围**：`cylinder_bottom / cnc_milling_machine`（Deckel Maho DMC-50H 铣床）的 frontside 工艺信号（`internal_machine_signals.h5`，PLC 电流/负载/扭矩等）+ 子工序时间戳 + 质检数据。
- **规模**：98 个"来料短"异常 + 39 个"夹持"异常 + 11 个"杂项"异常 + 正常件，每件一个 ProcessRun。
- **官方标注**：`anomaly`（0 正常 / 1 来料短 / 2 夹持 / 3 杂项）仅作事后对照，推理过程不用。
- **下载**：`engine/scripts/download_cipdmd.py [数据目录] [正常样本数]`（幂等，可重跑）。
- **改数据**：数据在 `/tmp/cipdmd`（可改 `CIPDMD_DATA` 环境变量指向别处）；替换 `signals/` 下的 h5 或 `quality_data.csv` 即可换一批演示样本。

## 结构

```
engine/
  engine/          一楼：契约层 + 推理核 + 分层溯源 + Ladybug 图 + 哈希审计 + FastAPI
  demo/            二楼：气动缸实例（深度本体 / TBox/ABox / 归因器 / LLM 服务 / 演示服务）
    knowledge/     知识文档（切块器成树入库）
  frontend/        React + Vite WEBUI（本体图 + 批量归因 + 推理链 + 对话）
  scripts/         数据下载 / 复现脚本
docs/
  prd/ ard/ research/   需求 / 架构 / 数据发现与设计记录
```

## 数据发现（docs/research/cip-dmd-layer2-blind-rule.md）

- 盲推规则：端面铣削电流/负载越出正常窗口判异常——异常1（来料短）99% 检出、正常误报 3.3%。
- 质检盲区：表面粗糙度严重超标的主因是"来料被锯短 4%"，质检称重线划太宽抓不住，靠铣削"空切"信号暴露。
