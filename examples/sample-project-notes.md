# LocalAgent 开发笔记

> 这是一份示例文档，用于演示 `LA add-file` 导入与知识库召回。内容均为虚构的项目记录，可安全用于演示。

## 架构决策

2026 年 7 月，LocalAgent 采用 **Hot / Warm / Cold** 三层记忆架构：

- **Hot**：`core_profile.json` 存放核心画像（姓名、偏好、长期目标）
- **Warm**：JSON memory / Hindsight 存放从对话与导入中提取的长期事实
- **Cold**：Chroma + BM25 混合检索，保留文档原文片段

设计原则是：换模型不换身份，记忆写入可审计、可撤销。

## 检索方案

知识库默认语义权重 `LA_SEMANTIC_WEIGHT=0.75`，BM25 补充关键词匹配。
长文档导入时，记忆提取与全文索引分离——RAG 索引全部 chunk，记忆仅提取高价值短句。

## 本地运行

项目在普通 Mac 上使用 **Ollama + qwen3.5:4b** 即可完整运行对话、记忆写入与检索。
关闭 Qwen3 thinking 模式（`OLLAMA_THINK=0`）后，简单问答通常在数秒内返回。

## 本周计划

- [ ] 补充 examples 目录，方便新用户上手
- [ ] 优化 workspace 待办扫描
- TODO: 支持更多文档格式导入
