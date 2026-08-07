# Git 开发规范

> 本文件是项目的协作 Agent（collab）开发规范，所有参与本仓库的 AI Agent 须无条件遵守。

## 🔴 硬约束

- **不请示不做**：没明确说的事不能做。可以提意见、可以随便想，但执行前必须请示。包括但不限于：commit、改配置、运行命令改系统状态、创建/删除文件、改版本号。
- **Git 由用户决定**：commit、版本号（major/minor）、分支操作、push——全部由用户说了算。patch 级别的 bug 修复 Agent 可自行决定。
- **用户违背规范时停下**：当用户指令与本规范冲突时，立刻停下工作，向用户指出冲突并确认意图，不擅自决定"用户优先"或"规范优先"。
- **拒绝 Demo 思维**：不接受"现在能用，遇到情况再说"。设计时考虑边界条件，实现时处理异常路径，不写"临时方案以后改"。

---

## Git 工作流

- 🟡 **做之前**：不擅自 commit，不擅自改版本号。
- 🔵 **做之后**：commit 前确认 ARCHITECTURE.md 最新、CHANGELOG.md 已更新。push 前先问用户要不要 commit。
- 🟡 **做之前**：任何**非简单修改**（新 feature / 模块重构 / 多文件改动）都开独立 branch，**Agent 必须主动请示开 branch**，不默认在 main 上直接改。在 branch 上可自行决定 commit。**合并到 main 必须用户主导**——用户没说合就不合。
- 🟢 **简单修改**（单行修复 / 小调整）：可直接在 main 改。
- 🔴 **合并严禁 fast-forward**：`git merge` 必须加 `--no-ff`，保留 branch 历史轨迹。禁止 `git merge`（默认 ff）和 `git rebase` 后快进合并。
- 🔴 **merge 回 main 的版本 = alpha 预发布版**：分支大改（feature/重构）merge 回 main 时，merge 的版本记为 `vX.Y.Z-alpha.N`（如 `v1.8.0-alpha.1`），**不是正式版**。后续要正式发布或处理分发版本时，才走 `vX.Y.Z-rc.N` → `vX.Y.Z`。patch 级小改例外，可直接正式版。

---

## 版本号

格式：`v<major>.<minor>.<patch>: 一句话简述`

| 位 | 含义 | 谁决定 |
|----|------|--------|
| major | 重大迭代（半成品=0，首个可用版=1） | Agent 建议，用户决定 |
| minor | feature 增/删/改 | Agent 建议，用户决定 |
| patch | bug 修复 / 小调整 | Agent 自行决定 |

版本名必须**短**：一句话说清改了什么，不罗列、不铺陈。

---

## 预发布后缀（alpha / beta / rc）

- 阶段：`alpha`（内部测试）< `beta`（公开测试）< `rc`（发布候选）< 正式版；**beta 一般不用**，通常只走 alpha → rc。
- 格式：`vX.Y.Z-阶段.编号`（如 `v2.0.0-alpha.1`、`v2.0.0-rc.1`），编号从 1 递增、无前导零。
- **仅用于 major/minor 发布前**；patch（bug 修复）不预发布，直接正式版。
- **后缀选择由用户决定**（与 major/minor 一致，Agent 只建议）；带后缀版本永远排在对应正式版之前。
- 案例：minor 迭代 `v1.8.0-alpha.1 → v1.8.0-alpha.2 → v1.8.0-rc.1 → v1.8.0`；发布后发现 bug 直接 `v1.8.1`，不再加后缀。

---

## 提交前文档检查

- 🔵 **做之后**：commit 前确认以下文档已同步：
  - **ARCHITECTURE.md**：结构改动同步更新。
  - **CHANGELOG.md**：独立文件（Keep a Changelog 标准）记录每个版本。版本块 `## [vX.Y.Z] - YYYY-MM-DD` 新版在上；分类 `Added`/`Changed`/`Deprecated`/`Removed`/`Fixed`/`Security`；顶部保留 `## [Unreleased]` 积攒未发布改动；每条目一句话讲对使用者的变化。
- 🔵 **做之前**：docs 体系——根目录 `README.md`（门面）/ `CHANGELOG.md`（版本史）/ `ARCHITECTURE.md`（架构）/ `ISSUES.md`（issue 总表）；`docs/adr/`（架构决策·技术选型）/ `docs/prd/`（产品需求）/ `docs/research/`（调研报告）/ `docs/issues/`（三状态文档）。docs 收「知识」，issue 收「工作」。
- 🔵 **做之前**：Issues **本地为主**（开源项目才同步 GitHub）——`ISSUES.md` 总表登记所有 issue（#/类型/优先级/目标版本/提出日期），不按状态分、不删；`docs/issues/{todo,doing,done}.md` 三状态文档装对应状态条目，状态流转 = 文件间移动。每条记 **提出 / 开始解决 / 解决** 三个日期（YYYY-MM-DD）。优先级 P0~P3，目标版本 = 排期。勾掉 = 解决（bug 要测试通过），done 条目不删。
