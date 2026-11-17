# CREDIT_BUDGET — Qoder Credits 使用策略

账号：Qoder 个人专业版（Pro）　文档核实日期：2026-11-17
本文档的目的：让每一份额度花在设计判断上，而不是花在重复扫描、反思循环和装饰性输出上。

## 1. 已核实的额度事实（官方文档）

| 事实 | 来源 |
| --- | --- |
| Pro 计划额度 2,000 Credits/月，当期结束清零、**不结转** | Pricing → Individual Plans |
| 活动赠送/签到额度单独计算，与 Plan Credits 分开 | Pricing → NOTE |
| 扣费顺序：先到期先扣；同期到期时先扣 Plan Credits 再扣 Add-on | Credits → Checking Your Credits |
| **模型请求失败不扣 Credits**，仅成功调用计费 | Credits → Error |
| 额度耗尽后仍可用 free basic models，受每日/每月上限约束 | Credits / Pricing |
| Credit Pack：$20 / 1,500 Credits，有效期 1 个月，不可退 | Pricing → Credit Packs |
| 消耗中位数参考：Editor Agent 模式 50K 上下文 ~3–4 Credits/请求，200K 上下文 ~7–12 Credits/请求；Qoder Agent 模式 200K ~50 Credits/请求；Repo Wiki ~50 Credits/仓库 | Credits → Task and Credits Consumption Guide |
| **Efficient 档限时 0.0x：付费用户选择 Efficient 不扣 Credits**（自动生效，无需兑换；高峰可能限速；子 Agent 自动调用的特定模型仍按公开倍率计费） | Events → Efficient Model Tier |
| Cloud Agents：模型调用按 token 折算 + **沙箱按 Session `running` 秒计费**（2026-08-10 起，pause/idle/terminated 不计费）；沙箱通常占 Session 总消耗 5%–10% | Cloud Agents → Billing |
| Cloud Agents 简单问答 ~1–3、文档生成 ~10–15、复杂多轮工具任务 ~20–50 Credits（估算，非计费依据） | Cloud Agents → Billing |
| Cloud Agents 个人 PAT：官方明确"不建议生产调度，仅用于测试/PoC" | Cloud Agents → Billing Warning |
| Cloud Agents 存储（对话历史、生成文件、附件、Skill 仓库）现阶段限免 | Cloud Agents → Storage |
| Sites：个人付费档可用，含 Database/Storage；**上线限免但有使用上限** | Sites |
| Qoder Desktop 账号余额在本机无可编程读取接口 | 本会话核实：官方文档无相应 CLI/API 供本地读取当前余额 |

> ⚠️ 重要推论：文档里的中位数只是统计估算，**不是账单**。真实余额与逐条扣费只能在 Qoder 网页 **Settings → Usage** 或客户端右下角 Credits 按钮查看。因此本文档给出的所有"预计消耗"是范围估计，不是承诺值。

## 2. 本项目的消耗规则（长期有效）

1. **模型档位在实现阶段选 Efficient**（0.0x），在需要设计判断的阶段才用高档位。
2. 一个时间只跑一个 Agent；不使用 Experts/多 Agent 并行，除非我明确要求并确认额度。
3. 不启用无限反思、自动重试、`/loop`、定时任务等会自我延续的机制。
4. 不重复扫描整个项目：探索只在阶段起点做一次，之后按文件精准读取。
5. 不批量生成装饰性文档；本项目文档固定 5 份，后续只在需求变化时改。
6. 不自动启动 Cloud Agent Session；Phase 3 若要用，先出预算再等确认。
7. 不做 LLM API 批处理：任何"逐篇 LLM 抽取"必须有上限、有缓存、可中断，并先报告预计调用数。
8. 不自动部署、不反复构建；生产构建只在阶段收尾验证一次。
9. 需要外部付费资源（API 额度、Cloud Pack、Credit Pack）时，先说明原因与用量再等确认。

## 3. 各 Phase 预计消耗与实际状态

| Phase | 内容 | Efficient 档预计 | 高档位（Performance/Ultimate）预计 | 外部 API 成本 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | 能力核实 + 项目初始化 + 5 份文档 + Literature Discovery 闭环 | ≈ 0（若选 Efficient；子 Agent 与网页抓取仍可能按倍率计费） | 约 50–150 | 0（公开学术 API 免费，无 key） | ✅ 完成 |
| 2 | Research Gap：多论文比较 + 6 类空白 + 三源反证检索 | ≈ 0 | 约 80–200 | 若启用可选 LLM 抽取：取决于自带头额度 | ✅ 完成（未启用 LLM） |
| 3 | Experiment Lab：冻结协议、两臂真实执行、独立 Evaluator | ≈ 0（本地执行） | 约 150–400 | 本地算力 0；**未使用 Cloud Agent** | ✅ 完成 |
| 4 | Evolution Lab：经验收集 → 6 类诊断 → 限额候选 → 回放 | ≈ 0 | 约 200–500 | **未使用 Cloud Agent**，确定性提议器 | ✅ 完成 |
| 5 | Skill Registry + 六条晋升门禁 + 回滚守卫 | ≈ 0 | 约 100–250 | 0 | ✅ 完成 |
| 6 | 18 步 Workflow + Research Dossier + 前端 11 页 | ≈ 0 | 约 150–350 | 0 | ✅ 完成 |
| 部署 | 前端静态托管（Sites 限免期） | 低 | 低 | Sites 限免，注意使用上限 | ⬜ **本轮不做** |

结论：**按上述规则，2,000 Credits/月足以覆盖 Phase 1–6 的开发**，前提是实现类工作放在 Efficient 档。
风险点集中在：(a) 需要深度推理的架构决策；(b) 可选 LLM 文献抽取的规模化；(c) Cloud Agent 沙箱时长。
本轮 (b) 与 (c) 均未触发。

## 4. 实际消耗（Phase 1–6，执行后填写）

| 项 | 结果 |
| --- | --- |
| Qoder Credits | **本机无余额读取接口，无法给出真实数字，因此不编造。** 需在网页 **Settings → Usage** 或客户端右下角 Credits 按钮核对 |
| Cloud Agent Session | **0 次**。真实实验执行改由本地 FastAPI 直接调用公开学术 API，零沙箱费用 |
| 外部 LLM API 调用 | **0 次**。服务端未配置 Provider Key，抽取 / 空白 / 诊断 / 提议全部走确定性规则，UI 与报告显式标注 Heuristic Mode |
| 部署 | **0 次**。未上线、未发布、未启用 Sites Database/Storage |
| 外部学术 API 请求 | OpenAlex / Crossref / arXiv 公开接口，免费、无需 key（可选 mailto 仅用于礼貌池标识）。实测样例：两条 workflow 文献检索分别 **14 次请求 / 0 缓存命中** 与 **15 次请求 / 3 缓存命中**（总查询 14 与 18），0 来源失败；每个实验臂总查询 3（回放臂由缓存服务，`requests_made=0, cache_hits=3`）；3 个真实 API 测试共 4 次请求（`cache_hits=0`）。**公开 API 无计费计数器，故不给出虚构的累计总额** |
| 生产构建次数 | 每阶段收尾各 1 次（`tsc -b && vite build`），无重复构建 |
| 测试运行 | 离线全量 235 passed / 3 skipped；真实 API 测试单独运行 3 passed |
| 子 Agent | 未启动并行子 Agent |

### 4.1 本轮发现的一个额度相关陷阱（已修复）

真实 API 测试原本可能被**磁盘缓存**服务：一次"3 passed"只用了 0.11 秒，
`cache_hits` 非零而 `requests_made=0`——这种"通过"什么都没验证，却会让人误以为真实检索已验收。
修复：三个 live 测试全部传 `refresh=True` 强制绕过缓存，并加 autouse fixture 在**本事件循环**上
关闭共享客户端（镜像 app lifespan）。修复后真实运行 9.25 秒、三源各返回 5 条真实记录、`cache_hits=0`。

同一原则也适用于实验成本统计：`total_api_queries = api_request_count + cache_hits`，
缓存命中**不会**让候选看起来更省预算。

## 5. 可选的 LLM 文献抽取：开关前的成本评估（尚未启用）

若要把数百篇论文的 method/dataset 抽取质量提上去：

- 朴素做法（每篇一次调用，无缓存）：300 次调用 → 明显不划算。
- 本项目要求：
  1. 批量分组（一次调用处理 10–20 篇摘要），
  2. 按 `paper_id + abstract_hash` 缓存，重跑零调用，
  3. 单次任务硬上限 `RLE_LLM_MAX_CALLS`（默认 20），
  4. 先用 20 篇做小样本试跑并报告实际用量，**再等确认扩大**。

## 6. 如果发现额度异常消耗

1. 立即停止当前任务，不再触发重试型循环。
2. 在网页 Settings → Usage → Credits log 定位消耗来源（模型档位、是否子 Agent 调用）。
3. 若确认为误用：反馈给 Qoder（客户端 Issue feedback），失败请求可申请核实——注意只有"模型请求失败"才不扣费。
