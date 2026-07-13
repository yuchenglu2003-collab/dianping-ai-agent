---
task_id: eda_wordcloud
goal: 对评论数据做清洗、探索性分析，并输出关键词词云与初步结论
deliverables:
  - clean_data
  - EDA分布图与时序图
  - 词云与关键词结论
acceptance:
  min_non_null_rate: 0.95
  figures_required: true
params:
  positive_threshold: 4
  drop_duplicates: true
report:
  title: 评论数据探索性分析报告
  sections: [数据概况, 分布与时序, 关键词洞察]
---

# 任务：评论数据 EDA 与词云

## 目标
对评论数据做清洗与探索性分析，并输出关键词词云。

## 数据
- 主表：由 CLI `--data` 指定

## 口径（可选）
- 好评：score >= 4

## 期望产出
1. 清洗后数据集
2. 评分/门店分布图、时序趋势图
3. 词云图与高频词结论（Markdown）

## 验收标准
- 清洗后关键字段非空率 >= 95%
- 图表文件存在且可打开
- 报告中数字均可追溯到 metrics
