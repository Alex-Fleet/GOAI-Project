# Changelog

本项目所有显著变更都记录在此文件中，格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [v0.2.1] - 2026-08-13

### Added

- 层2 盲推规则验证（docs/research/cip-dmd-layer2-blind-rule.md）：DMC-50H 端面铣削主轴电流+负载均值越出正常窗口判铣削异常——正常 0/15 误报、异常1 检出 93%、异常2 检出 87%，物理机制自洽（空切/过载）
- 数据发现：表面粗糙度严重超标主因是来料缺陷（70/99 官方 anomaly=1 原料短）而非设备自身，来料质检重量全部合格（质检盲区），与 PRD 层2 预设冲突
- 本体推理复现验证（engine/scripts/blind_repro.py）：能复现"铣削异常→设备可疑"、正常不误报；暴露 L2 缺来料侧工艺信号导致误归设备
- Demo 设计与能力边界记录（docs/research/demo-design-notes.md）：展示口径 vs 实际能力对照、落地开发清单、诚实口径

### Changed

- 二楼实例化方向由数据校准：demo 追责主线指向来料缺陷（而非 PRD 预设的设备自身）

## [v0.2.0] - 2026-08-13

### Added

- 一楼知识入库（D6）：engine/engine/kb/——结构感知切块 → LLM 三元组抽取 → 人审 → 幂等 MERGE 入 Ladybug 图 + bge-m3 向量 + Jieba/BM25 双索引（payload 带实体引用）
- 检索两路接入推理循环（ARD §4.4）：`TracingLoop(retriever=...)` L1 检索兜底挂载点 + 候选关联校验 + basis 真实经推理核把关（防伪命中）
- 前端工作台（D3）：engine/frontend/——React 18 + Vite 5 + @xyflow/react 双栏（左 SSE 流式叙事 + 右推理路径图 + 处置确认）
- 演示服务：engine/scripts/serve.py（默认 8800）——图遍历直连 / 检索兜底 / 未知对象 FAILED 三条定位路径
- 新增检索兜底 / 图查询 backward 方向 / KB 入库测试（65 用例全绿）

### Changed

- ARD goai-agent-platform-ard 状态改为已实现，补 §4.4 检索起点与 §9 实现状态

### Fixed

- Ladybug backward 查询方向 bug：返回真实图方向（src -(rel)-> dst），修复检索兜底的反向工艺回溯被推理核沿图验证误拒

## [v0.1.0] - 2026-08-12

### Added

- 新增 PRD：工业质量事故追责与全局处置 Agent（docs/prd/goai-quality-agent-prd.md）
- 新增一楼 ARD：通用分层溯源 Agent + 平台（docs/ard/goai-agent-platform-ard.md，契约先行）
- 新增故事+demo ARD（docs/ard/goai-quality-agent-ard.md）
- 一楼引擎实现（engine/）：Ladybug 属性图库 + 自研推理核（7 步链 + 提议→把关小循环）+ 哈希链审计 + FastAPI SSE，模拟事实测试 21 用例全绿

### Changed

- 行业从半导体晶圆制造调整为 CiP-DMD 气动缸离散制造（真实数据驱动定位 demo 主线）
- 故事 vs demo 框架定稿：通用方法层 vs 气动缸实例（DMC-50H 铣床主线）
- LLM 职责全文档同步为三职责：NLU 解析 + 探索提议 + 人话表达（决策结论由推理核把关）
- Demo 工作台改为双栏 codex 式（左 agent 聊天窗流式 + 右内容区）

## [v0.0.3] - 2026-08-07

### Added

- 新增参赛 Idea v2：工业质量事故追责与全局处置 Agent（docs/idea_v2.md）
- inv_v1.md 格式规范化

## [v0.0.2] - 2026-08-07

### Added

- 新增 AGENT.md 协作开发规范（Git 工作流、版本号、预发布后缀、提交前文档检查）

## [v0.0.1] - 2026-08-07

### Added

- 初始版本：工业制造 AI Agent 竞赛方案（docs/inv_v1.md）
