# README 重构与 AGENTS.md 技术架构收敛 — 实施计划

## 目标

1. **README.md → 业务功能导向**：面向使用者/决策者，讲清平台能解决什么问题、提供哪些业务能力、典型场景、如何快速上手。移除/收敛偏技术细节。
2. **新建 AGENTS.md → 技术架构真相源**：承接 README 中现有偏技术的内容（技术栈、系统架构图、项目结构、API 端点概览、部署运维命令），作为开发者与 AI 代理的入口。
3. **CLAUDE.md 处置**：待确认（见下方决策点）。

## 内容拆分

### README.md（业务功能版）— 拟包含章节

1. 标题 + 一句话定位（企业级 AI 应用平台）
2. 为什么需要 AI-Studio（企业痛点 → 平台价值，业务语言）
3. 核心业务能力矩阵（用户视角，列表/卡片式）
   - 多租户企业级隔离（数据不串租户）
   - 统一 AI 模型管理（OpenAI / Anthropic / Azure / Ollama 等，API Key 加密）
   - 知识库 RAG（文档上传→解析→向量化→语义检索）
   - 智能 Agent（ReAct + 工具绑定 + SSE 流式对话）
   - 可视化工作流（DAG 编排，React Flow 画布）
   - 插件生态（OpenAPI 规范第三方集成）
   - 监控审计与配额（审计日志、Token 统计、细粒度 RBAC）
4. 典型应用场景（如企业知识助手、自动化工作流、内部 Agent 中台）
5. 快速体验（一句指引 + 指向 Docker 一键部署）
6. 了解更多（链接：AGENTS.md 技术架构 / docs 设计文档 / 在线 API 文档）
7. License

### AGENTS.md（技术架构版）— 拟包含章节（主要来自 README 现有内容迁移）

1. 文档定位与分工说明（指向 CLAUDE.md 编码约定、docs/ 设计文档）
2. 技术栈（后端/前端表格）
3. 系统架构图（ASCII 拓扑）
4. 项目结构树（backend / frontend / docs）
5. 关键技术约定（精简摘要，详述指向 CLAUDE.md）
6. 开发 / 运行 / 测试指南（后端 uvicorn+alembic、前端 dev/build/lint）
7. API 端点概览表（`/api/auth`、`/api/agents` …）
8. Docker 部署与运维命令（从 README 迁移）
9. 参考文档链接

## 不改动

- `docs/` 下设计文档保持不变。
- 视 CLAUDE.md 决策而定（见下）。

## 验证方式

- 文档类任务无单元测试；完成后人工复核：内部/外部链接有效、README 与 AGENTS.md 内容无重复与分叉、技术细节不外漏到 README 业务视角。

## 交付物

- 修改后的 `README.md`
- 新建的 `AGENTS.md`

---

## 决策点：CLAUDE.md 如何处置

当前 `CLAUDE.md` 已承载编码约定（多租户隔离、BaseRepository、异常体系、SSE 规范等），与计划中的 AGENTS.md（架构）存在少量概述重叠。需确认：

- **A. 保持 CLAUDE.md 不变**：AGENTS.md 在开头说明两者分工并相互引用，避免重复与分叉。（推荐，改动最小、风险最低）
- **B. 合并到 AGENTS.md 并删除 CLAUDE.md**：单一技术真相源，但 Claude Code 默认读取 CLAUDE.md 的兼容性下降。
- **C. 将 CLAUDE.md 精简为指向 AGENTS.md 的薄指针**：保留 CLAUDE.md 文件名以兼容工具，内容仅做引用。
