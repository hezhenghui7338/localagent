#!/usr/bin/env bash
# Hindsight 记忆引擎一键演示（隔离数据目录，不污染 data/）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export LA_DATA_DIR="${LA_DATA_DIR:-/tmp/la-hindsight-demo}"

echo "==> 数据目录: $LA_DATA_DIR"
rm -rf "$LA_DATA_DIR"

echo ""
echo "==> 0/6 清空隔离 bank（不影响日常 data/）"
LA reset-memory --keep-knowledge

echo ""
echo "==> 1/6 记忆后端诊断"
LA memory-status

echo ""
echo "==> 2/6 写入决策演变链（6 条记忆）"
LA add "2026年3月，开发者决定用 Python 重写个人助手，项目代号 LocalAgent"
LA add "2026年5月，架构评审后放弃 SQLite，改用 Hindsight 作为 Warm 层记忆引擎"
LA add "2026年6月，团队曾考虑回退到 JSON 存储，因为 Hindsight 安装包体积较大"
LA add "2026年7月，最终决定保留 Hindsight，因为 reflect 推理和 4 路并行 recall 不可替代"
LA add "技术偏好：所有个人数据必须留在 Mac 本地，不上传云端"
LA add "LocalAgent 默认模型是 qwen3.5:4b，通过 Ollama 本地运行"

echo ""
echo "==> 3/6 语义 recall"
LA search "记忆引擎选型"

echo ""
echo "==> 4/6 时间感知 recall"
LA search "2026年5月 决定" --verbose

echo ""
echo "==> 5/6 标签浏览"
LA memories --list-tags
LA memories --tag 决策 --sort newest --limit 5

echo ""
echo "==> 6/6 reflect 跨记忆推理"
LA reflect "LocalAgent 的记忆引擎选型经历了怎样的变化？最终为什么保留 Hindsight？"

echo ""
echo "演示完成。数据在 $LA_DATA_DIR"
echo "详细说明见 examples/hindsight-demo.md"
