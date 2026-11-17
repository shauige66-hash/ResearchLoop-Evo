# PRD — ResearchLoop Evo

版本：v0.1（Phase 1）　日期：2026-11-17　状态：Phase 1 已实现，Phase 2+ 未启动

## 1. 背景与问题

科研工作的第一公里最难：一个研究方向被提出后，研究者要花数周读文献才能确认"哪里真的还没人做"、"这个 idea 是否已被做过"。现有 AI 工具解决的是**问答**（给定 PDF 回答问题），而不是**研究过程本身**。

现有工具的三个失效点：

1. **幻觉引用**：生成看起来合理但不存在的论文、DOI、作者。
2. **无证据边界**：把模型推断和论文作者的观点混为一谈，读者无法分辨。
3. **闭环断裂**：只输出综述文本，不能设计实验、不能验证、不能从失败中改进。

## 2. 产品定位

**ResearchLoop Evo = 证据约束的科研闭环智能体。**

- 证据约束：任何结论都能回溯到具体论文的具体证据片段。
- 科研闭环：文献 → 空白 → 实验 → 验证 → 技能改进 → 独立评测晋升。
- 与 PDF 问答工具的区别：本产品的输出是**可证伪的研究判断与实验记录**，不是摘要拼接。

目标用户：高校研究生 / 早期研究者 / AI Agent 方向求职者与评审。

## 3. 目标与非目标

### 3.1 产品目标（全周期）

| # | 目标 | 衡量方式 |
| --- | --- | --- |
| G1 | 输入研究方向，产出真实可追溯的相关文献集 | 引用可解析率 100%，零编造论文 |
| G2 | 结构化提取方法/数据集/指标/局限 | 每字段有 `evidence_source`，人工抽检准确率 ≥ 80% |
| G3 | 提出候选研究空白并附文献证据链 | 每个空白列出支持它的论文与原文片段 |
| G4 | 设计并真实执行最小可行实验 | 实验日志、原始输出、随机种子可复现 |
| G5 | 独立验证实验结果 | 验证 Agent 不共享执行 Agent 的上下文 |
| G6 | 从失败轨迹提炼 Skill 并版本化 | Skill diff 可追溯至具体失败轨迹 |
| G7 | 通过独立评测决定是否晋升新版本 | 未达门禁阈值的版本不得替换当前版本 |

### 3.2 Phase 1 范围（本阶段交付）

实现 G1、G2 的可运行最小闭环，并交付文献对比矩阵与文献研究报告。

### 3.3 Phase 1 明确非目标

- ❌ 自动得出最终研究创新结论（研究空白属于 Phase 2）
- ❌ 实验设计、执行、验证（Phase 3）
- ❌ GEPA、Skill 自进化、版本晋升门禁（Phase 4/5）
- ❌ 全文抓取与付费库绕过（合规红线）
- ❌ 正式公开发布部署
- ❌ 引入向量数据库 / Redis / K8s / 微服务

## 4. Phase 1 用户故事与验收标准

### US-1 研究方向输入
作为研究者，我输入一个具体研究方向并限定领域、年份、论文类型与关键词，以便得到范围可控的文献集。

验收：
- 输入字段：研究主题、研究领域、时间范围（from/to）、论文类型多选、关键词列表、是否优先综述、来源多选、结果上限。
- 关键词可由用户扩展，也可由系统从主题自动切分补全（自动补全结果需在 UI 标注为"系统扩展"）。
- 非法输入（无主题、年份倒置、上限越界）返回 422 与具体原因，前端内联提示。

### US-2 真实文献检索
作为研究者，我需要结果全部来自真实学术 API，且能追溯来源。

验收：
- 至少接入 OpenAlex + Crossref，arXiv 可选启用。
- 每条记录含 `source`（来源标识）与 `source_url`（可点击原始记录页）。
- 支持多关键词多来源合并、DOI 归一化去重（`https://doi.org/10.X` ≡ `10.X`）、标题相似度去重（阈值可配置，默认 token 相似度 ≥ 0.85 判重）。
- 支持年份筛选、相关性排序、综述优先识别（`type=review` 或标题/摘要含 survey/review/systematic review 线索）。
- 单来源失败不影响整体：返回 `source_errors`，页面显示真实错误与重试入口。
- 空结果显示空态并给可执行建议（放宽年份/增加关键词），不返回伪造条目。
- 相同查询在缓存 TTL 内命中缓存，不重复请求外部 API。

### US-3 文献结构化整理（Paper Schema）
验收：
- 统一 schema 字段齐备：`paper_id title authors publication_year venue doi abstract research_problem method dataset evaluation_metrics findings limitations future_work source_url evidence_status` + provenance。
- 每个抽取字段附 `FieldEvidence { value, evidence_source, evidence_span, confidence }`。
- Phase 1 抽取只使用摘要：无摘要或未识别出的字段 → `evidence_source = none`、`value = null`、`evidence_status = unknown`，并汇总进 `missing_fields`。
- 允许用户将字段改为 `manual` 并保存（人工补充是合法来源）。
- 严禁把摘要中不存在的内容写入字段。

### US-4 文献对比矩阵
验收：
- 从 Library 勾选 ≥ 2 篇论文生成矩阵：论文 / 研究问题 / 方法 / 数据集 / 指标 / 主要结果 / 局限性。
- 单元格保留证据来源标记，点击可展开原文片段与来源链接。
- 单元格可编辑，编辑后标记为 `manual` 并保留修改时间。
- 支持导出 CSV 与 JSON（导出内容含 evidence_source，便于二次核查）。

### US-5 文献研究报告
验收：
- 报告含 7 节：主题概览、相关研究分类、代表性论文、方法比较、已有结论、已知局限、尚待验证问题。
- **三类内容强制分离**：`facts`（论文中直接可查）、`author_claims`（论文作者的观点，注明出处论文）、`system_inference`（本系统的推断，必须写明推断依据与不确定性）。
- 所有引用以 `paper_id` 锚定，可跳转回 Library。
- "尚待验证问题"不得写成结论；Phase 1 明确声明本阶段不产出最终研究创新点。

### US-6 成本与合规
验收：
- Phase 1 全流程零 LLM 调用、零 Cloud Agent、零部署。
- API Key / mailto 只存在于后端 `.env`，不进入前端代码与构建产物。
- 外部请求具备超时（默认 20s）、每来源限速、有界重试（最多 2 次）、缓存（默认 24h）。

## 5. 页面与信息架构

| 页面 | 状态 | 核心职责 |
| --- | --- | --- |
| Research Dashboard | 已实现 | 项目与研究运行概览、最近检索、来源健康度 |
| Literature Discovery | 已实现 | 研究方向输入、多源检索、结果预览 |
| Literature Library | 已实现 | 论文列表、筛选、字段与证据查看、人工补充 |
| Literature Matrix | 已实现 | 对比矩阵、证据展开、CSV/JSON 导出 |
| Research Report | 已实现 | 报告生成与三类内容分离查看 |
| Research Gap | 占位 | Phase 2：候选空白与证据链 |
| Experiment Lab | 占位 | Phase 3：实验设计、执行、独立验证 |
| Evolution Lab | 占位 | Phase 4：失败轨迹与 Skill 进化 |
| Skill Registry | 占位 | Phase 5：Skill 版本与晋升评测门禁 |

## 6. 未来模块接口边界（Phase 1 只定义，不实现）

```
POST /api/gaps/discover     {topic_id, paper_ids[]}  -> GapCandidate[]        # Phase 2
POST /api/experiments/design {gap_id}               -> ExperimentSpec        # Phase 3
POST /api/experiments/run    {experiment_id}         -> RunRecord + artifacts# Phase 3
POST /api/experiments/verify {run_id}                -> VerificationReport   # Phase 3（独立上下文）
POST /api/evolve/skills      {trajectory_ids[]}      -> SkillDiff[]          # Phase 4
POST /api/skills/evaluate    {skill_version}          -> EvaluationReport    # Phase 5
POST /api/skills/promote     {skill_version, gate}   -> PromotionDecision    # Phase 5
```

Phase 1 中以上端点返回 `501 Not Implemented`，且响应体内含所属 Phase 与阻塞原因。

## 7. 成功指标（Phase 1）

| 指标 | 目标 |
| --- | --- |
| 引用真实性 | 抽检 30 条，100% 可在来源 URL 验证 |
| 去重有效性 | DOI 完全重复率 0%；明显重复标题（同篇跨源）合并率 ≥ 90% |
| 证据可追溯 | 100% 抽取字段带 `evidence_source`；`unknown` 字段不出现在报告事实区 |
| 闭环可用性 | 从输入主题到导出 CSV/生成报告，一条链路无人工干预完成 |
| 离线测试 | 单元测试不联网即可全绿；真实 API 冒烟测试可单独开启 |
