# Changelog

本项目所有显著变更都记录在此文件中，格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

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
