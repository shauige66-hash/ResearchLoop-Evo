# ResearchLoop Evo

**Evidence-grounded Autonomous Research & Self-Evolving Agent**
基于文献证据与实验验证的自进化科研智能体。

用户输入一个具体研究方向，系统的目标是自主完成：文献检索 → 结构化整理 → 研究空白提出 → 最小实验设计与执行 → 失败轨迹提炼 Skill → 独立评测决定版本晋升。

> 当前进度：**Phase 1（Literature Discovery）已完成可运行闭环**。研究空白发现、实验执行、自进化与 Skill 晋升均未实现，导航中对应入口会明确返回"未实现"，不会伪装执行。

---

## 1. 真实性承诺

这个项目的第一原则是**可追溯**，宁可留空也不编造：

| 承诺 | 实现方式 |
| --- | --- |
| 论文、作者、DOI、年份、摘要全部来自真实 API | OpenAlex / Crossref / arXiv 实时检索，代码中无任何硬编码论文列表 |
| 未获取到的字段必须标记缺失 | `evidence_status = unknown` + `missing_fields`，绝不猜测填充 |
| 只读了摘要不能假装读了全文 | 每个抽取字段带 `evidence_source`（`abstract` / `fulltext` / `manual` / `model_inference`）与原文 `evidence_span` |
| 网络失败要显示真实错误 | 后端原样返回 HTTP 状态与原因，前端展示错误条与重试按钮，不回退到假数据 |
| 没有假按钮和假动画 | 占位模块调用真实返回 501 的接口，UI 显示未实现而不是"完成" |

## 2. 技术栈

- 前端：React 18 + TypeScript + Vite + Tailwind CSS + Recharts + React Router
- 后端：Python 3.13 + FastAPI + Pydantic v2 + httpx
- 数据：SQLite（标准库 `sqlite3`）+ 文件型 HTTP 缓存；无 Redis、无向量库、无 Docker
- LLM：Phase 1 **零模型调用**，抽取全部为确定性规则；LLM 抽取为默认关闭的可选扩展

## 3. 快速开始

```bash
# 1) 后端
cd ResearchLoop-Evo/backend
python -m venv .venv
source .venv/Scripts/activate        # Windows Git Bash
pip install -r requirements.txt
cp .env.example .env                 # 建议填 mailto=<你的邮箱> 进入各 API 的礼貌池
uvicorn app.main:app --reload --port 8000

# 2) 前端（另一个终端）
cd ResearchLoop-Evo/frontend
npm install
npm run dev                          # http://localhost:5173
```

浏览器打开 http://localhost:5173 → **Literature Discovery** → 输入研究方向 → Start Search。
首次真实检索约 5–15 秒（取决于来源数量与 arXiv 限流情况）。

### 测试与构建

```bash
cd backend && python -m pytest -q                 # 离线单元测试，不联网
RLE_LIVE_TESTS=1 python -m pytest -q tests/test_live_sources.py   # 可选：真实 API 冒烟测试
cd frontend && npm run build                      # tsc + vite build
```

## 4. 目录结构

```
ResearchLoop-Evo/
├── README.md  PRD.md  ARCHITECTURE.md  CREDIT_BUDGET.md  TASKS.md
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI 入口与路由注册
│   │   ├── config.py          超时/限流/缓存/API 开关
│   │   ├── models/            Paper、检索请求、矩阵、报告 schema
│   │   ├── services/
│   │   │   ├── sources/       openalex.py crossref.py arxiv.py
│   │   │   ├── http.py        共享客户端：限流 + 重试 + 缓存
│   │   │   ├── normalize.py   原始记录 → Paper（含 provenance）
│   │   │   ├── dedupe.py      DOI 归一 + 标题相似度去重
│   │   │   ├── rank.py        相关性与综述优先排序
│   │   │   ├── extract.py     证据化启发式抽取
│   │   │   ├── pipeline.py    检索编排（多源合并/失败聚合）
│   │   │   ├── report.py      文献研究报告生成
│   │   │   └── export.py      CSV / JSON 导出
│   │   └── storage/store.py   SQLite 持久化
│   └── tests/
└── frontend/src/
    ├── pages/                 Dashboard / Discovery / Library / Matrix / Report + 4 个占位页
    ├── components/  api/  lib/  types/
```

## 5. Phase 路线图

| Phase | 内容 | 状态 |
| --- | --- | --- |
| 1 | Literature Discovery：检索、去重、结构化、对比矩阵、报告 | ✅ 本阶段完成 |
| 2 | Research Gap：基于证据链的候选研究空白与理由 | ⬜ 未开始 |
| 3 | Experiment Lab：最小可行实验设计与真实执行、结果独立校验 | ⬜ 未开始 |
| 4 | Evolution Lab：失败轨迹 → Skill 改进（含 GEPA 式变体搜索） | ⬜ 未开始 |
| 5 | Skill Registry + 独立评测晋升门禁 | ⬜ 未开始 |

## 6. 已知限制

- arXiv API 对单 IP 限流严格（实测返回 `429 Rate exceeded`），已做 ≥3 秒间隔与失败降级；批量检索时 arXiv 可能缺失，页面会显示该来源的真实失败原因。
- Crossref `/works` 默认不返回摘要，摘要主要来自 OpenAlex；缺失时前端显示"摘要缺失"而非空字符串假装存在。
- 未抓取任何付费全文；`method` / `dataset` / `findings` 在 Phase 1 均由摘要规则抽取，`evidence_source` 一律为 `abstract`，需要全文或人工补充时由用户编辑。
- 详见 `CREDIT_BUDGET.md` 关于额度与部署能力的核实结果。
