# TASKS — ResearchLoop Evo

状态标记：`[x]` 已完成并验证 · `[~]` 代码完成待验证 · `[ ]` 未开始
本文件是唯一进度真相来源；每阶段结束时更新，不并行推进多个 Phase。

## Phase 0 · 环境与能力（已完成）

- [x] 检查工作区，确认不改动旧项目 `labtrace`
- [x] 确认本机工具链：node v24.14.1 / npm 11.11.0 / python 3.13.9 / git 2.53
- [x] 官方文档核实 Sites、Sites DB/Storage、Cloud Agents 计费与 SSE、Credits 规则
- [x] 实测学术 API 连通性：OpenAlex 200、Crossref 200、arXiv 429（限流，需 ≥3s）
- [x] 架构决策：本地 FastAPI + SQLite，前端 React/Vite，Phase 1 零 LLM 零 Cloud Agent

## Phase 1 · Literature Discovery（本阶段）

### 1.1 文档基线
- [x] README.md
- [x] PRD.md
- [x] ARCHITECTURE.md
- [x] CREDIT_BUDGET.md
- [x] TASKS.md

### 1.2 后端
- [x] 项目骨架、依赖清单、`.env.example`（含 mailto、限速、超时、TTL、开关）
- [x] Paper / FieldEvidence / 请求响应 Pydantic 模型 + 证据一致性校验
- [x] `http.py`：令牌桶限速、有界重试、文件缓存、真实错误对象
- [x] `sources/openalex.py`：search / filter / 摘要倒排还原 / review 识别
- [x] `sources/crossref.py`：query.bibliographic / DOI / select 字段
- [x] `sources/arxiv.py`：Atom 解析 + ≥3s 间隔 + 429 降级
- [x] `normalize.py`：三源统一 → Paper（含 `source_url`、`missing_fields`）
- [x] `dedupe.py`：DOI 归一 + 标题 token/序列相似度合并
- [x] `rank.py`：相关度 + 关键词覆盖 + 年份近因 + 综述加分
- [x] `extract.py`：摘要切句 + 线索词分类 + `evidence_span` 逐字保留
- [x] `pipeline.py`：多关键词×多来源编排、失败聚合、缓存命中统计
- [x] `store.py`：SQLite（projects / runs / papers / paper_edits）
- [x] `report.py`：7 节报告 + 事实 / 作者观点 / 系统推断分离
- [x] `export.py`：矩阵 CSV（BOM，Excel 中文安全）与 JSON
- [x] API 路由：search / runs / papers / detail / 字段人工补充 / matrix / export / report / health
- [x] 未来模块路由返回 501（gaps / experiments / evolve / skills）
- [x] 离线单元测试（归一、去重、抽取、pipeline、API）
- [x] 可选真实 API 冒烟测试（默认跳过，`RLE_LIVE_TESTS=1` 开启）

### 1.3 前端
- [x] Vite + React + TS + Tailwind + Recharts + Router 配置
- [x] 侧边导航：5 实页 + 4 占位（带 Phase 标记）
- [x] Research Dashboard：run 概览、年份分布、来源占比、最近检索
- [x] Literature Discovery：输入表单、关键词扩展、来源勾选、进度与真实错误
- [x] Literature Library：过滤（年份/来源/综述/证据状态/搜索）、分页、详情抽屉、人工补充
- [x] Literature Matrix：勾选生成、证据展开、单元格编辑、CSV/JSON 导出
- [x] Research Report：7 节报告与三类内容分离展示
- [x] 占位页调用真实 501 接口并显示"未实现 + 所属 Phase"
- [x] `npm run build` 通过

### 1.4 收尾
- [x] 后端 pytest 全绿 + 前端 build 成功
- [x] 真实一次端到端检索验证（本机 API 实测）
- [ ] 用户检查与确认

## Phase 2 · Research Gap（已完成，commit 82abba3）

- [x] `ResearchGap` 12 字段契约，Pydantic 强制"至少两篇不同论文 + 逐字证据"
- [x] 6 类空白检测（method / evaluation / generalization / reliability / efficiency / reproducibility）
- [x] 禁止单篇 Future Work 推断空白；必须跨论文比较方法与实验范围
- [x] 每个候选自动对 OpenAlex / Crossref / arXiv 构造反证检索，命中则降级为 Low
- [x] 未找到反证只表述"当前检索范围内未发现"，绝不表述"不存在"
- [x] 置信度为有依据的 Low / Medium / High 标签 + rationale，非统计概率
- [x] 默认 `needs_human_review`；人工接受 / 拒绝 / 改写落库
- [x] 新增 `agent_architecture` / `memory_strategy` / `skill_strategy` 抽取字段
- [x] 无 LLM Provider，全链路显式标注 Heuristic Mode
- [ ] 可选 LLM 抽取增强（未启用；需先出额度预算并等确认，见 CREDIT_BUDGET §5）

## Phase 3 · Experiment Lab（后端 + 前端已完成并实测）

- [x] 单一 Agent-Evolution 模板；假设标注 `under_test`，非既定结论
- [x] `BenchmarkCase` + Development / Validation / Holdout 按 topic 分组切分（防泄漏）
- [x] 参考 DOI 经 Crossref / OpenAlex 真实核验；人工 `confirmed_by` 才成为 Ground Truth
- [x] 未确认参考集 → `awaiting_reference_set`，允许检索、禁止晋升，不编造覆盖率
- [x] 独立纯 Python Evaluator：Coverage@K / Missed Refs / API 查询数 / 唯一论文数 / 执行时间
- [x] 成本口径含缓存命中（`api_request_count + cache_hits`），暖缓存不能掩盖额外检索
- [x] 冻结协议：来源 / 年份 / Top-K / 请求上限对两臂一致；Candidate 不得改评测与基准
- [x] 原始响应快照落盘 + `POST /verify` 从快照独立重算并比对
- [x] Holdout 在候选锁定前关闭，锁定后仅允许一次
- [x] 六条晋升规则实现于 `promotion_blockers`，门禁未通过时列出全部真实原因
- [x] Experiment Lab 页面：基准 / Skill / 设计 / 执行 / 复核 / 历史对比
- [ ] 图表像素级视觉验收（受环境限制，见"已知限制"）

## 已知限制

- **Recharts 图表未能视觉验收**：应用内浏览器视口塌陷（`window.innerWidth === 0`、
  `innerHeight === 0`，`take_screenshot` 返回 `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`），
  `ResponsiveContainer` 测得宽度 0，因此不挂载 SVG surface。已尝试 3 次（等待、
  强制父容器 1000px、读取 React fiber）均无法在此环境取得非零尺寸。
  控制台无任何错误；图表数据绑定已用真实 API 数据核对：
  development / validation 各两臂，baseline `api_queries=3`、candidate `api_queries=6`、
  `unique_papers=20`，全部来自已落库的 run 记录，无静态数字。
  **结论：数据绑定为真，像素渲染未验证**，需在正常浏览器中复核。
- **自进化实验尚未通过最终验收**：3 个基准案例的参考 DOI 已真实核验但**未经人工确认**，
  覆盖率保持 `null`，晋升门禁关闭。交付的是可运行流程 + 待标注基准。
- **真实数据发现**：6 次真实检索中 arXiv 对最终 top-k 的贡献均为 0，OpenAlex 主导。
  该现象由 `source_coverage_insufficient` 诊断如实报告；由于 OpenAlex 已排在首位，
  系统同时说明"仅重排来源无法弥补这部分覆盖"，不夸大修复效果。
- **回滚正向路径仅有离线测试覆盖**：真实库中尚无 archived 版本（晋升始终被正确拒绝），
  因此无法在真实数据上演示一次成功回滚。回滚守卫（拒绝从未 active 的版本）已实测。
- **LLM 提议器未在真实 Provider 上运行**：服务端未配置 Key，实测走确定性回退并显式标注原因。
  LLM 路径的校验、限额与失败回退由离线测试覆盖。

## Phase 4 · Evolution Lab（已完成并实测）

- [x] 经验收集：从已落库 ExperimentRun + 原始快照还原真实试验信号
- [x] 6 类失败诊断，每条附触发它的真实数字；无信号则不产生诊断
- [x] 诊断不把 API 传输失败归咎于 prompt；预算截断不算 API 失败
- [x] 统一 `CandidateProposer`：默认确定性，可选限额 LLM（1 次/轮，Pydantic 校验 + 预算钳制）
- [x] 每轮最多 3 个候选，记录父版本 / 变异描述 / 来源试验 / 改动组件 / 创建时间
- [x] 候选查询数由**实测基线成本 × 1.5** 推导，不会一出生就超预算
- [x] 变异只使用 development 试验；validation / holdout 的参考标题与年份不外泄
- [x] 缺证据时拒绝编造变异，并写明拒绝原因（如无确认参考集）
- [x] 需要改动冻结协议的诊断只报告、不产生候选
- [x] `source_priority` 与 `search_filters` 变为真实生效：前者置换冻结来源集合影响
      稳定排序的并列裁决，后者只能收窄冻结年份窗口
- [x] Evolution Lab 页面：协议选择 / 轮次历史 / 预算推导 / 诊断 / 被拒绝变异 / 候选 / 真实经验

## Phase 5 · Skill Registry & Promotion（已完成并实测）

- [x] 版本不可覆盖；新 Run 读取 Active Version；历史 Run 保留自身 Skill Snapshot
- [x] `POST /api/skills/evaluate`：真实执行两臂并由独立 Evaluator 打分
- [x] `POST /api/skills/promote`：六条门禁全过才激活，否则 409 + 全部真实原因
- [x] `POST /api/skills/rollback`：只能回到曾经 active 的版本，绕过门禁但不声称提升
- [x] Skill Registry 页面：可进化边界 / 版本总览 / 快照与事件 / 晋升决策 / 变更历史
- [x] 晋升被拒时前端完整展示服务端返回的逐条原因
- [ ] 正式部署决策与访问范围（本轮不做）

## 明确不做（避免范围蔓延）

- ❌ 向量数据库、Redis、Kubernetes、微服务拆分
- ❌ 付费全文抓取或绕过订阅墙
- ❌ 假数据、假按钮、假执行动画
- ❌ 未经确认的自动部署与 Cloud Agent 长任务
