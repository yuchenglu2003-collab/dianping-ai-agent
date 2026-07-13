# 大众点评数据分析 AI Agent 实现计划（LLM 驱动版）

> **核心定位**：必须配置大模型 API 密钥才能运行。  
> Agent 用大模型 **理解任务、规划步骤、撰写报告**；数值计算仍由本地 Python 工具完成。

---

## 1. 产品定义

### 1.1 这是什么

一个 **LLM-native 数据分析 Agent**：

| 输入 | 说明 |
|------|------|
| **数据集** | 上传 CSV / Excel / Parquet（评论、门店、行为、销量等） |
| **任务要求** | 自然语言描述（Web 文本框 或 Markdown/YAML） |
| **API 密钥** | **必填**。OpenAI 兼容接口（OpenAI / DeepSeek / 通义 / 本地代理等） |

| 输出 | 说明 |
|------|------|
| **Markdown 分析报告** | 主产出；LLM 基于真实 metrics 撰写，图表内嵌 |
| **清洗后数据** | 任务涉及清洗时附带 `clean_data.csv` |
| **图表 / 模型** | 作为报告附件，供 LLM 引用 |

### 1.2 不是什么

- ❌ 不是「无密钥也能跑的规则脚本」
- ❌ 不是让 LLM 直接算 PV/RFM/F1（数字必须来自 Tool）
- ❌ 不是按「第几周」固定流程；完全由 **数据 + 任务** 驱动

### 1.3 启动门槛

```
无 API Key → 拒绝启动（UI / CLI 均提示配置）
有 API Key → 探查数据 → LLM 理解任务 → 规划 → 执行 → LLM 写报告
```

---

## 2. 使用方式

### 2.1 Web UI（推荐）

1. 填写 **API 密钥**（或读取 `.env` 中已配置的密钥）
2. 上传 **数据集**
3. 文本框输入 **任务要求**
4. 点击「开始分析」→ 看进度条 → 阅读 / 下载 Markdown 报告

```bash
./start_ui.sh
# http://localhost:8501
```

### 2.2 CLI

```bash
# 密钥写在 .env：DEEPSEEK_API_KEY=sk-...
python -m src.cli run --data data/uploads/xxx.csv --task "清洗并做EDA和词云"
```

### 2.3 密钥配置方式

| 方式 | 优先级 | 说明 |
|------|--------|------|
| UI 输入框 | 最高（当次会话） | 不落盘，仅内存 |
| 环境变量 `DEEPSEEK_API_KEY` | 中 | 本地开发推荐 |
| `.env` 文件 | 中 | 项目根目录，已 gitignore |
| `config/config.yaml` 的 `llm.api_key` | 低 | 不推荐明文写入 |

**安全约定**：密钥禁止写入 git、报告、日志、`state.json`。

---

## 3. Agent 流程（LLM 介入点）

```
┌─────────────┐
│  API Key    │─── 未配置则终止
└──────┬──────┘
       ▼
┌─────────────┐     ┌──────────────────┐
│  数据集      │────▶│  data_profile    │  （本地 Tool，不调用 LLM）
└─────────────┘     └────────┬─────────┘
                             │ schema 摘要
┌─────────────┐              ▼
│  任务要求    │────▶┌──────────────────┐
└─────────────┘     │  LLM TaskParser   │  理解意图 → TaskSpec JSON
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │  LLM Planner     │  选 Tool → TaskPlan DAG
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │  Feasibility     │  字段是否够（规则 + LLM 说明）
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │  Executor        │  本地 Tools 执行（确定性）
                    └────────┬─────────┘
                             │ metrics + artifacts
                             ▼
                    ┌──────────────────┐
                    │  Critic          │  规则验收 + LLM 解读偏差
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │  LLM Reporter    │  写 Markdown 报告（引用 metrics）
                    └────────┬─────────┘
                             ▼
                      最终 report.md
```

### LLM 负责 vs 不负责

| LLM 负责 | 本地 Tool 负责 |
|----------|----------------|
| 理解模糊任务 | 读表、清洗、聚合 |
| 规划用哪些分析步骤 | 绘图、分词、训练模型 |
| 撰写报告叙述与洞察 | 计算 PV/RFM/F1 等指标 |
| 解释失败原因 | 落盘 parquet/csv/png |
| 澄清口径歧义（可选） | 固定随机种子复现 |

**铁律**：报告中的每个数字必须能追溯到 `metrics.json`；LLM 不得编造。

---

## 4. 总体目标与成功标准

| 维度 | 目标 |
|------|------|
| 智能 | 用户用口语描述任务，LLM 能规划合理分析路径 |
| 可信 | 结论绑定 metrics；Critic 拦截无来源数字 |
| 可用 | 无密钥时明确报错，有密钥时一键跑通 |
| 可复现 | Tool 层固定 seed；LLM 温度偏低（0–0.3） |
| 可观测 | 记录 LLM 调用次数、token、每步耗时 |

**验收标准：**

1. 未配置密钥 → UI/CLI 无法开始分析
2. 配置密钥后 → 给定数据 + 自然语言任务 → 产出报告
3. 报告由 LLM 生成，且包含嵌入图表 / 清洗数据（如任务需要）
4. 同一数据 + 同一任务，Tool 产出 metrics 可复现
5. 密钥不出现在任何产出文件中

---

## 5. 系统架构（角色）

```
┌─────────────────────────────────────────────────────────┐
│                    Orchestrator                          │
│  密钥校验 / 断点续跑 / 进度回调 / Human Gate             │
└────────────┬──────────────────────────────┬───────────┘
             │                              │
┌────────────▼────────────┐    ┌────────────▼────────────┐
│  LLM TaskParser         │    │  LLM Planner            │
│  自然语言 → TaskSpec     │    │  TaskSpec+Schema → DAG  │
└────────────┬────────────┘    └────────────┬────────────┘
             │                              │
┌────────────▼──────────────────────────────▼────────────┐
│                    Executor + Tool Registry              │
│  profile · clean · plot · nlp · ml · business · ...     │
└────────────┬────────────────────────────────────────────┘
             │
┌────────────▼────────────┐    ┌─────────────────────────┐
│  Critic（规则+LLM）      │    │  LLM Reporter           │
│  验收项 / 防编造         │    │  metrics → Markdown     │
└─────────────────────────┘    └─────────────────────────┘
             │
┌────────────▼────────────────────────────────────────────┐
│  LLM Gateway（统一鉴权、重试、结构化输出、用量统计）       │
└─────────────────────────────────────────────────────────┘
```

---

## 6. 能力模块（Tools，本地执行）

Planner（LLM）从工具目录中选用，不按周绑定：

| 能力域 | Tools | 典型触发场景 |
|--------|-------|--------------|
| 数据 | `data_profile`, `clean_table` | 清洗、探查 |
| 可视化 | `plot_distributions`, `eda_timeseries` | EDA、分布、时序 |
| NLP | `tokenize_jieba`, `make_wordcloud` | 词云、关键词 |
| 归因 | `aspect_share_analysis`, `length_rating_attribution` | 好评归因 |
| ML | `build_text_features`, `train_compare_models`, `tune_model` | 评分预测 |
| 商业 | `funnel_metrics`, `rfm_segment`, `pay_behavior_analysis` | 漏斗、RFM |
| 预测 | `forecast_sales`, `anomaly_detect` | 销量、异常 |

新增能力 = 新 Tool + 注册到 Tool Catalog（供 LLM 选型）。

---

## 7. LLM 交互设计

### 7.1 TaskParser 输出示例

```json
{
  "goal": "清洗评论数据，做EDA和词云，输出报告",
  "deliverables": ["clean_data", "charts", "wordcloud", "report"],
  "acceptance": {"need_clean_data": true, "need_figures": true},
  "params": {"positive_threshold": 4},
  "clarifications": []
}
```

### 7.2 Planner 输出示例

```json
{
  "feasibility": "feasible",
  "steps": [
    {"id": "profile", "tool": "data_profile"},
    {"id": "clean", "tool": "clean_table", "depends_on": ["profile"]},
    {"id": "plot", "tool": "plot_distributions", "depends_on": ["clean"]},
    {"id": "tokenize", "tool": "tokenize_jieba", "depends_on": ["clean"]},
    {"id": "wordcloud", "tool": "make_wordcloud", "depends_on": ["tokenize"]},
    {"id": "report", "tool": "llm_render_report", "depends_on": ["plot", "wordcloud"]}
  ]
}
```

### 7.3 Reporter 输入

- `TaskSpec.goal`
- `metrics.json`（完整）
- 图表路径列表 + 清洗数据摘要（前 N 行）
- **禁止**传入全量原始表

### 7.4 Reporter 输出

- 结构化 Markdown：`# 标题` → 任务回顾 → 数据概况 → 发现 → 图表 → 结论 → 建议
- 图表用相对路径嵌入；词云/分布图/png 或 html 链接

---

## 8. 仓库结构（目标态）

```
美团ai-agent/
├── plan.md / architecture.md
├── .env.example              # DEEPSEEK_API_KEY= / DEEPSEEK_BASE_URL=
├── config/config.yaml        # llm 默认模型、温度（不含密钥）
├── src/
│   ├── agent/
│   │   ├── task_parser.py    # LLM 解析任务
│   │   ├── planner.py        # LLM 规划（主路径）
│   │   ├── orchestrator.py
│   │   └── critic.py
│   ├── infra/
│   │   └── llm_gateway.py    # 必实现：chat + structured JSON
│   ├── tools/                # 确定性工具
│   └── ui/app.py             # 密钥输入 + 双输入 + 进度 + 报告
├── artifacts/
└── logs/runs/{run_id}/
    ├── llm_calls.json        # 调用审计（不含 key）
    └── ...
```

---

## 9. 分阶段实现路线

### Phase 0：密钥与 Gateway（必须先做）

- [ ] `.env.example` + 启动时密钥校验
- [ ] 实现 `LLMGateway`（OpenAI 兼容 SDK）
- [ ] UI 增加密钥输入；无密钥禁用「开始分析」
- [ ] `setup-check` 增加「密钥可用性探测」（轻量 ping）

### Phase 1：LLM TaskParser + Planner

- [ ] 自然语言任务 → `TaskSpec` / `TaskPlan` JSON
- [ ] Tool Catalog 注入 Prompt；约束只能选已注册工具
- [ ] 保留规则 Planner 仅作 **LLM 失败时的降级**（可选，需日志标明）

### Phase 2：LLM Reporter

- [ ] 替换模板报告为 `llm_render_report` Tool
- [ ] Prompt：强制引用 metrics；Critic 检查「报告数字 ⊆ metrics」
- [ ] 报告内嵌图表 + 按需附清洗数据

### Phase 3：体验与可信

- [ ] 进度条 + LLM 阶段状态（「正在理解任务…」「正在撰写报告…」）
- [ ] `llm_calls.json` 用量统计
- [ ] 任务歧义时 LLM 返回 `clarifications`（UI 追问）

### Phase 4：高级分析能力

- [ ] 归因、评分预测、漏斗/RFM、销量预测等 Tools
- [ ] LLM 根据任务自动组合（不再扩规则表）

---

## 10. 配置契约

### `.env`（推荐）

```bash
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

### `config/config.yaml`

```yaml
llm:
  required: true                    # 必须为 true
  provider: deepseek
  base_url: https://api.deepseek.com/v1
  model: deepseek-chat
  model: gpt-4o-mini                # 或 deepseek-chat 等
  temperature: 0.2
  max_tokens: 4096
  timeout_sec: 60
  max_retries: 2

orchestrator:
  block_without_api_key: true
```

---

## 11. 风险与缓解

| 风险 | 缓解 |
|------|------|
| LLM 编造指标 | Reporter 只读 metrics；Critic 校验数字来源 |
| 密钥泄露 | 仅 .env / 环境变量；日志脱敏；UI 密码框 |
| 规划选错 Tool | Tool Catalog + JSON Schema 校验；失败重试 |
| 成本过高 | 控制 Prompt 长度；schema 摘要而非全表；缓存 TaskPlan |
| LLM 不可用 | 明确报错；可选降级规则 Planner（需用户确认） |
| 中文任务理解差 | System Prompt 中文；示例 few-shot |

---

## 12. 人机边界

| 人 | Agent（LLM + Tools） |
|----|----------------------|
| 提供 API 密钥 | 校验并使用 |
| 上传数据、写任务 | LLM 理解并规划 |
| 确认敏感口径（可选） | 按理解执行 + 报告注明假设 |
| 最终对外背书 | 生成报告初稿 |

---

## 13. 与当前代码的差距（待开发）

| 现状 | 目标 |
|------|------|
| `llm.enabled: false` | 改为 `required: true`，无 key 阻断 |
| `RulePlanner` 为主 | `LLMPlanner` 为主 |
| 模板 `render_report` | `llm_render_report` |
| UI 无密钥栏 | 首屏配置密钥 |
| `LLMGateway` 未实现 | 完整实现 + 测试 |

---

## 附录：一句话

**「没密钥不能跑；有密钥后，LLM 懂任务、写报告，数字由 Python 工具算。」**
