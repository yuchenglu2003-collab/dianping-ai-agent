# 大众点评数据分析 AI Agent（LLM 驱动）

**必须配置 API 密钥**。大模型负责理解任务、规划步骤、撰写报告；数值计算由本地 Python 工具完成。

设计文档：[`plan.md`](./plan.md)、[`architecture.md`](./architecture.md)。

## 快速开始

```bash
cd "美团ai-agent"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 配置 DeepSeek 密钥
cp .env.example .env
# 编辑 .env：
# DEEPSEEK_API_KEY=sk-你的密钥
# DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
# DEEPSEEK_MODEL=deepseek-chat

./start_ui.sh
# 打开 http://localhost:8501
```

界面三步：

1. 填写 **API 密钥**（或已在 `.env` 配置）
2. 上传 **数据集**
3. 文本框填写 **任务要求** → 开始分析

## CLI

```bash
python -m src.cli setup-check
python -m src.cli run --data data/raw/sample_reviews.csv --task "清洗数据，做EDA和词云，写分析报告"
```

## 架构要点

| 模块 | 说明 |
|------|------|
| Auth Gate | 无密钥拒绝启动 |
| LLM TaskParser | 自然语言 → TaskSpec |
| LLM Planner | TaskSpec + Schema → 执行 DAG |
| Tools | 本地清洗/绘图/分词等 |
| LLM Reporter | 基于 metrics 写 Markdown 报告 |

## 产出

- 报告：`artifacts/reports/{task}_{run_id}/report.md`
- 清洗数据：同目录 `clean_data.csv`（如任务需要）
- LLM 用量：`logs/runs/{run_id}/llm_calls.json`
