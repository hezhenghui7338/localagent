# Action Planner Benchmark

Multi-step local action scenarios for comparing Simple ReAct vs Milestone planning.

## Scenarios

| ID | Prompt | Expected tools (approx) |
|----|--------|-------------------------|
| find-edit | 找到 src 下 config 里的 timeout，改成 30 | grep/read → edit |
| find-run | 搜索 README 里安装步骤，然后运行 pytest | grep/read → run_shell |
| glob-read | 用 glob 找 *.py 配置文件，读第一个 | glob → read_file |

## Run

```bash
# Compare with planner on/off (requires local Ollama model)
LA_PLANNER_ENABLED=0 python benchmarks/action/run.py
LA_PLANNER_ENABLED=1 python benchmarks/action/run.py
```

## Metrics

- **completion**: heuristic pass/fail per scenario
- **tool_calls**: number of tool invocations
- **llm_calls**: router.chat invocations
- **partial**: milestone mode partial completion flag
