# LocalAgent 测试用例审查目录

> 更新于 **2026-07-16** · E2E 离线约 **110+** 条（含 journeys/pending/websearch/safety/graph）· 默认 `pytest` 含 STM · CI 另跑 `e2e-offline`
>
> 建议审查顺序：Config/Models → Memory → Agent/Tools → Ingest/Tasks → CLI/UX → Audit → E2E → Benchmark
>
> **验收真源**：[`docs/PRD.md`](PRD.md) §6 + [`examples/product-tour.zh-CN.md`](../examples/product-tour.zh-CN.md) 验收清单（本目录为用例索引，非完整验收矩阵）。

## 分类概览

| 分类 | 数量 |
|------|------|
| [Config/Models](#configmodels) | 69 |
| [Memory](#memory) | 130+（含 pending/observe/cold/neo4j/temporal 等新单测） |
| [Agent/Tools](#agenttools) | 111+ |
| [Ingest/Tasks](#ingesttasks) | 14+ |
| [CLI/UX](#cliux) | 93 |
| [Audit](#audit) | 20 |
| [E2E](#e2e) | ~110 offline + 7 live |
| [Benchmark](#benchmark) | 9 + STM (`test_stm_benchmark.py`，进日常 CI) |

## PRD §6 ↔ E2E 映射

| 验收项 | 主要自动化 | 状态 |
|--------|------------|------|
| §6.1 安装/配置/chat 外壳 | `test_la_ops` version/config/setup/chat help | ✅ offline |
| §6.2 跨会话 Warm | `test_la_journeys.test_journey_cross_session_warm_recall`；live chat 召回 | ✅ / live |
| §6.2 pending 确认门 | `test_la_pending` | ✅ |
| §6.2 Cold 先于 Warm | `test_la_journeys` chatgpt/chat cold；收紧的 ingest 断言 | ✅ |
| §6.2 rag 不写 Warm | `test_journey_rag_does_not_create_warm` | ✅ |
| §6.2 reset 清 Cold 对话块 | `test_journey_reset_chatgpt_clears_cold_archive` | ✅ |
| §6.3 websearch / 不入库 | `test_la_websearch` | ✅ |
| §6.3 危险硬拦 / 审批 / 幻觉 | `test_la_safety` | ✅ |
| §6.3 无意图预检 | `test_e2e_safety_no_intent_precheck_before_tools` | ✅ |
| §6.4 audit HTML | `test_journey_audit_report_html` | ✅ |
| 可选 Neo4j `memory://` | `test_la_graph` | ✅ P2 |
| Observe / STM | unit + `test_stm_benchmark`（非 CLI e2e） | ✅ CI |

## E2E 核心命令覆盖（目标 ≥3）

子进程真实调用 `python -m localagent.cli`（`tests/e2e/`，marker: `e2e` / `e2e_live`）。

| 命令 | 关联用例数 | 状态 |
|------|-----------|------|
| `memory add` | 16+ | ✅ |
| `memory search` | 14+ | ✅ |
| `memory query` | 5 | ✅ |
| `memory pending/approve/reject` | 5 | ✅ |
| `memory reflect` | 5 | ✅ |
| `memory forget` | 3 | ✅ |
| `memory reset` | 6+ | ✅ |
| `memory ingest` | 10+ | ✅ |
| `memory consolidate` | 4 | ✅ |
| `memory status` | 9 | ✅ |
| `memory reindex` | 4 | ✅ |
| `memory graph` (neo4j memory://) | 1 | ✅ |
| `rag add` | 27+ | ✅ |
| `rag search` | 16+ | ✅ |
| `rag ingest` | 9 | ✅ |
| `rag status` | 9 | ✅ |
| `rag reset` | 7 | ✅ |
| `rag rebuild` | 6 | ✅ |
| `websearch` | 3 | ✅ |
| `tasks` | 6 | ✅ |
| `workspace` | 4 | ✅ |
| `audit` | 5+ | ✅ |
| `config` | 5 | ✅ |
| `setup` | 3 | ✅ |
| `chat` | 9+ | ✅ |

**E2E 文件分工**

| 文件 | 职责 |
|------|------|
| `e2e/test_la_commands.py` | 冒烟：help / add / rag / search / forget / reset / tasks |
| `e2e/test_la_memory.py` | Warm：status / query / reflect smoke / consolidate / ingest / reindex |
| `e2e/test_la_rag.py` | Cold：add / ingest / search / status / reset / rebuild |
| `e2e/test_la_ops.py` | chat / config / workspace / audit / setup / tasks 运维 |
| `e2e/test_la_completion.py` | Tab 补全 |
| `e2e/test_la_journeys.py` | PRD 旅程：跨会话 / Cold-first / rag 边界 / reset Cold / audit HTML |
| `e2e/test_la_pending.py` | pending / approve / reject 确认门 |
| `e2e/test_la_websearch.py` | websearch CLI + 不入库 |
| `e2e/test_la_safety.py` | 护栏 / 审批 / 幻觉 / 无意图预检 |
| `e2e/test_la_graph.py` | Neo4j `memory://` 冒烟 |
| `e2e/test_la_live.py` | 需 Ollama 的实机语义检索 / reflect / chat / 跨 session |

运行：

```bash
pytest                            # CI 主 job：排除 e2e / e2e_live；含 STM
pytest tests/e2e/ -m e2e          # CI e2e-offline job
pytest tests/e2e/ -m e2e_live     # 实机 Ollama（本机）
```

## Config/Models

### `test_core.py`（9）

#### 1. `test_value_filter`

- **意图**：覆盖: value filter
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`not is_valuable('好的'); is_valuable('2026年7月决定使用 Hindsight 作为记忆引擎')`
- **位置**：`test_core.py:15-17` · 意图由函数名推断

#### 2. `test_should_retain_as_memory`


- **意图**：覆盖: should retain as memory
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`should_retain_as_memory('2026年7月决定使用 Hindsight 作为记忆引擎', heading='# 日记'); should_retain_as_memory('今天决定用 Hindsight 做记忆引擎。', heading='# 日记'); not should_retain_as_memory('x' * 900, heading='## 附录'); not should_retain_as_memory('- item\n- item\n- item\n- item\n- item', heading='## 参考'); should_retain_as_memory('rebuild memory test content', heading='# Rebuild')`
- **位置**：`test_core.py:20-30` · 意图由函数名推断

#### 3. `test_temporal_intent_month`

- **意图**：覆盖: temporal intent month
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`intent.intent_kind == 'range'; intent.anchor_date == '2026-05-15'; intent.scope_start == '2026-05-01'; intent.scope_end == '2026-05-31'`
- **位置**：`test_core.py:33-38` · 意图由函数名推断

#### 4. `test_temporal_intent_year`

- **意图**：覆盖: temporal intent year
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`intent.intent_kind == 'range'; intent.anchor_date is not None; '2024' in intent.anchor_date`
- **位置**：`test_core.py:41-45` · 意图由函数名推断

#### 5. `test_rrf_fusion`

- **意图**：覆盖: rrf fusion
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`len(fused) == 2; fused[0]['chunk_id'] in ('a', 'b')`
- **位置**：`test_core.py:48-53` · 意图由函数名推断

#### 6. `test_scoped_recall_finds_added_memory`

- **意图**：覆盖: scoped recall finds added memory
- **输入**：无外部夹具
- **方法**：CLI/subprocess
- **校验**：`hits; any(('Hindsight' in h['text'] for h in hits))`
- **位置**：`test_core.py:56-60` · 意图由函数名推断

#### 7. `test_scoped_recall_matches_chinese_preference_query`

- **意图**：覆盖: scoped recall matches chinese preference query
- **输入**：无外部夹具
- **方法**：CLI/subprocess
- **校验**：`hits; any((poem in h['text'] for h in hits))`
- **位置**：`test_core.py:63-68` · 意图由函数名推断

#### 8. `test_search_memory_falls_back_to_knowledge`

- **意图**：覆盖: search memory falls back to knowledge
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`'记忆未命中' in result; 'Hindsight' in result`
- **位置**：`test_core.py:71-85` · 意图由函数名推断

#### 9. `test_search_memory_falls_back_to_documents`

- **意图**：覆盖: search memory falls back to documents
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`'记忆和 RAG 均未命中' in result; 'Hindsight' in result`
- **位置**：`test_core.py:88-103` · 意图由函数名推断


### `test_env_config.py`（28）

#### 1. `test_load_model_servers_from_yaml`

- **意图**：覆盖: load model servers from yaml
- **输入**：参数: config_setup
- **方法**：unit
- **校验**：`[s.provider for s in servers] == ['ollama', 'openai', 'openrouter']; servers[1].api_key == 'old-openai-key'`
- **位置**：`test_env_config.py:60-64` · 意图由函数名推断

#### 2. `test_write_model_servers_to_yaml`

- **意图**：覆盖: write model servers to yaml
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`loaded[0]['provider'] == 'aiping'`
- **位置**：`test_env_config.py:67-74` · 意图由函数名推断

#### 3. `test_parse_model_servers_json`

- **意图**：覆盖: parse model servers json
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`servers[0].provider == 'aiping'`
- **位置**：`test_env_config.py:77-80` · 意图由函数名推断

#### 4. `test_compute_provider_priority_default_order`

- **意图**：覆盖: compute provider priority default order
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`compute_provider_priority(servers, '') == ['ollama', 'aiping']`
- **位置**：`test_env_config.py:83-88` · 意图由函数名推断

#### 5. `test_add_model_server`

- **意图**：覆盖: add model server
- **输入**：参数: config_setup
- **方法**：unit
- **校验**：`path == yaml_path; was_update is False; names == ['ollama', 'openai', 'openrouter', 'aiping']`
- **位置**：`test_env_config.py:91-104` · 意图由函数名推断

#### 6. `test_remove_model_server`

- **意图**：覆盖: remove model server
- **输入**：参数: config_setup
- **方法**：unit
- **校验**：`existed is True; path == yaml_path; 'openai' not in names`
- **位置**：`test_env_config.py:107-113` · 意图由函数名推断

#### 7. `test_set_server_api_key`

- **意图**：覆盖: set server api key
- **输入**：参数: config_setup
- **方法**：unit
- **校验**：`openrouter.api_key == 'sk-or-new'`
- **位置**：`test_env_config.py:116-121` · 意图由函数名推断

#### 8. `test_set_server_model`

- **意图**：覆盖: set server model
- **输入**：参数: config_setup
- **方法**：unit
- **校验**：`ollama.model == 'llama3.2:3b'`
- **位置**：`test_env_config.py:124-129` · 意图由函数名推断

#### 9. `test_set_server_model_rejects_auto`

- **意图**：覆盖: set server model rejects auto
- **输入**：参数: config_setup
- **方法**：raises
- **校验**：`(隐式/副作用校验)`
- **位置**：`test_env_config.py:132-135` · 意图由函数名推断

#### 10. `test_init_model_servers_config`

- **意图**：覆盖: init model servers config
- **输入**：夹具: tmp_path, monkeypatch
- **方法**：monkeypatch + temp data
- **校验**：`result.config_path.is_file(); result.created is True; env_config.read_env_value(env_path, 'LA_MODEL_SERVERS_FILE') == 'config/model_servers.yaml'`
- **位置**：`test_env_config.py:138-154` · 意图由函数名推断

#### 11. `test_cli_config_list`

- **意图**：覆盖: cli config list
- **输入**：参数: config_setup; 夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; 'model_servers.yaml' in out; 'openai' in out; 'ollama→openai→openrouter' in out`
- **位置**：`test_env_config.py:157-163` · 意图由函数名推断

#### 12. `test_cli_config_add_json`

- **意图**：覆盖: cli config add json
- **输入**：参数: config_setup; 夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; any((s.provider == 'aiping' for s in servers))`
- **位置**：`test_env_config.py:166-171` · 意图由函数名推断

#### 13. `test_cli_config_remove`

- **意图**：覆盖: cli config remove
- **输入**：参数: config_setup; 夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; all((s.provider != 'openai' for s in servers))`
- **位置**：`test_env_config.py:174-178` · 意图由函数名推断

#### 14. `test_cli_config_set_key`

- **意图**：覆盖: cli config set key
- **输入**：参数: config_setup; 夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; openrouter.api_key == 'sk-test'`
- **位置**：`test_env_config.py:181-186` · 意图由函数名推断

#### 15. `test_cli_config_set_key_from_stdin`

- **意图**：覆盖: cli config set key from stdin
- **输入**：参数: config_setup; 夹具: monkeypatch, capsys
- **方法**：monkeypatch + CLI/subprocess + stdout
- **校验**：`rc == 0; openai.api_key == 'stdin-key'`
- **位置**：`test_env_config.py:189-196` · 意图由函数名推断

#### 16. `test_init_model_servers_config_reload_existing`

- **意图**：覆盖: init model servers config reload existing
- **输入**：参数: config_setup; 夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; 'model_servers.yaml' in out; '无变更' in out`
- **位置**：`test_env_config.py:199-204` · 意图由函数名推断

#### 17. `test_init_model_servers_config_force_reports_overwrite`

- **意图**：覆盖: init model servers config force reports overwrite
- **输入**：参数: config_setup; 夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; '覆盖' in out or '变更' in out`
- **位置**：`test_env_config.py:207-214` · 意图由函数名推断

#### 18. `test_ensure_config_reloads_from_disk`

- **意图**：覆盖: ensure config reloads from disk
- **输入**：参数: config_setup
- **方法**：unit
- **校验**：`config.get_model_server('openrouter').api_key == 'disk-updated-key'; any(('openrouter' in line and 'API Key' in line for line in result.change_lines()))`
- **位置**：`test_env_config.py:217-232` · 意图由函数名推断

#### 19. `test_yaml_list_order_is_priority`

- **意图**：覆盖: yaml list order is priority
- **输入**：参数: config_setup
- **方法**：unit
- **校验**：`[s.provider for s in config.MODEL_SERVERS] == ['ollama', 'openrouter', 'openai']; list(config.MODEL_PROVIDER_PRIORITY) == ['ollama', 'openrouter', 'openai']; list(result.priority_after) == ['ollama', 'openrouter', 'openai']`
- **位置**：`test_env_config.py:235-247` · 意图由函数名推断

#### 20. `test_cli_config_list_reflects_yaml_order`

- **意图**：覆盖: cli config list reflects yaml order
- **输入**：参数: config_setup; 夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; 'ollama→openrouter→openai' in out`
- **位置**：`test_env_config.py:250-262` · 意图由函数名推断

#### 21. `test_auto_bootstrap_uses_packaged_templates`

- **意图**：After pip install, checkout templates are absent; package resources must work.
- **输入**：夹具: tmp_path, monkeypatch
- **方法**：monkeypatch + temp data
- **校验**：`created is not None; created.is_file(); (project / 'config' / 'model_servers.yaml').is_file(); env_path.is_file(); 'LA_MODEL_SERVERS_FILE' in env_path.read_text(encoding='utf-8')`
- **位置**：`test_env_config.py:265-280` · 有 docstring

#### 22. `test_auto_bootstrap_skips_when_yaml_exists`

- **意图**：覆盖: auto bootstrap skips when yaml exists
- **输入**：参数: config_setup
- **方法**：unit
- **校验**：`again == yaml_path; env_config.read_env_value(env_path, 'LA_MODEL_SERVERS_FILE') == 'config/model_servers.yaml'`
- **位置**：`test_env_config.py:283-287` · 意图由函数名推断

#### 23. `test_reload_model_servers_with_file`

- **意图**：覆盖: reload model servers with file
- **输入**：参数: config_setup
- **方法**：unit
- **校验**：`'openai' in config.VALID_PROVIDERS; config.get_model_server('openai').api_key == 'old-openai-key'`
- **位置**：`test_env_config.py:290-294` · 意图由函数名推断

#### 24. `test_apply_config_flags_provider_and_tavily`

- **意图**：覆盖: apply config flags provider and tavily
- **输入**：参数: config_setup
- **方法**：unit
- **校验**：`ollama.base_url == 'http://127.0.0.1:11434'; ollama.model == 'qwen3.5:4b'; env_config.read_env_value(env_path, 'TAVILY_API_KEY') == 'tvly-test'; any(('TAVILY_API_KEY' in line for line in result.change_lines()))`
- **位置**：`test_env_config.py:297-310` · 意图由函数名推断

#### 25. `test_cli_config_flat_flags`

- **意图**：覆盖: cli config flat flags
- **输入**：参数: config_setup; 夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; '已写入' in out; ollama.base_url == 'http://localhost:9999'; env_config.read_env_value(config_setup[0], 'TAVILY_API_KEY') == 'tvly-cli'`
- **位置**：`test_env_config.py:313-332` · 意图由函数名推断

#### 26. `test_cli_config_from_json_file`

- **意图**：覆盖: cli config from json file
- **输入**：参数: config_setup; 夹具: tmp_path, capsys
- **方法**：CLI/subprocess + stdout + temp data
- **校验**：`rc == 0; openrouter.api_key == 'sk-or-json'; env_config.read_env_value(config_setup[0], 'TAVILY_API_KEY') == 'tvly-json'`
- **位置**：`test_env_config.py:335-347` · 意图由函数名推断

#### 27. `test_cli_config_example`

- **意图**：覆盖: cli config example
- **输入**：夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; '"provider": "ollama"' in out; 'TAVILY_API_KEY' in out; 'qwen3.5:4b' in out`
- **位置**：`test_env_config.py:350-356` · 意图由函数名推断

#### 28. `test_normalize_config_argv`

- **意图**：覆盖: normalize config argv
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_normalize_config_argv(['config', 'list']) == ['config', 'list']; _normalize_config_argv(['config', '--provider', 'ollama']) == ['config', 'set', '--provider', 'ollama']; _normalize_config_argv(['config', 'foo.json']) == ['config', 'apply', 'foo.json']`
- **位置**：`test_env_config.py:359-369` · 意图由函数名推断


### `test_ollama_setup.py`（5）

#### 1. `test_ensure_ollama_ready_skips`

- **意图**：覆盖: ensure ollama ready skips
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`result.skipped is True; isinstance(result, OllamaSetupResult)`
- **位置**：`test_ollama_setup.py:8-12` · 意图由函数名推断

#### 2. `test_has_model_matches_prefix`

- **意图**：覆盖: has model matches prefix
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`has_model('qwen3.5:4b') is True; has_model('missing') is False`
- **位置**：`test_ollama_setup.py:15-21` · 意图由函数名推断

#### 3. `test_ensure_ollama_ready_declines_install`

- **意图**：覆盖: ensure ollama ready declines install
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`result.declined is True; result.skipped is True; result.installed is False; '跳过' in result.message`
- **位置**：`test_ollama_setup.py:24-33` · 意图由函数名推断

#### 4. `test_ensure_ollama_ready_installs_when_user_accepts`

- **意图**：覆盖: ensure ollama ready installs when user accepts
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`calls == ['install', 'pull']; result.installed_now is True; result.pulled_now is True; result.model_ready is True`
- **位置**：`test_ollama_setup.py:36-69` · 意图由函数名推断

#### 5. `test_ensure_ollama_ready_assume_yes_skips_prompt`

- **意图**：覆盖: ensure ollama ready assume yes skips prompt
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`calls == ['install']; result.model_ready is True`
- **位置**：`test_ollama_setup.py:72-102` · 意图由函数名推断


### `test_project_root.py`（4）

#### 1. `test_packaged_resources_readable`

- **意图**：覆盖: packaged resources readable
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`read_text('env.example') is not None; 'LA_MODEL_SERVERS_FILE' in read_text('env.example'); read_text('model_servers.yaml.example') is not None; 'provider: ollama' in read_text('model_servers.yaml.example'); read_text('core_profile.example.json') is not None`
- **位置**：`test_project_root.py:13-19` · 意图由函数名推断

#### 2. `test_resolve_project_root_honors_la_home`

- **意图**：覆盖: resolve project root honors la home
- **输入**：夹具: tmp_path, monkeypatch
- **方法**：monkeypatch + temp data
- **校验**：`config.resolve_project_root() == home.resolve()`
- **位置**：`test_project_root.py:22-26` · 意图由函数名推断

#### 3. `test_resolve_project_root_source_checkout`

- **意图**：覆盖: resolve project root source checkout
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`(root / 'pyproject.toml').is_file(); (root / 'src' / 'localagent').is_dir(); config.IS_SOURCE_CHECKOUT is True`
- **位置**：`test_project_root.py:29-33` · 意图由函数名推断

#### 4. `test_resolve_project_root_installed_uses_user_home`

- **意图**：Wheel layout: config.py under site-packages → default ~/.localagent.
- **输入**：夹具: tmp_path, monkeypatch
- **方法**：monkeypatch + temp data
- **校验**：`config.resolve_project_root() == expected.resolve()`
- **位置**：`test_project_root.py:36-50` · 有 docstring


### `test_router.py`（23）

#### 1. `test_resolve_exact_model_match`

- **意图**：覆盖: resolve exact model match
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`router.resolve_ollama_model() == 'qwen3.5:4b'`
- **位置**：`test_router.py:25-29` · 意图由函数名推断

#### 2. `test_resolve_fallback_by_tag`

- **意图**：覆盖: resolve fallback by tag
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`router.resolve_ollama_model() == 'qwen3.5:4b'`
- **位置**：`test_router.py:32-37` · 意图由函数名推断

#### 3. `test_resolve_skips_embedding_only`

- **意图**：覆盖: resolve skips embedding only
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`router.resolve_ollama_model() == 'qwen3.5:4b'`
- **位置**：`test_router.py:40-48` · 意图由函数名推断

#### 4. `test_list_provider_models_ollama`

- **意图**：覆盖: list provider models ollama
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`router.list_provider_models('ollama') == ['qwen3.5:4b']`
- **位置**：`test_router.py:51-58` · 意图由函数名推断

#### 5. `test_list_provider_models_openai_compatible`

- **意图**：覆盖: list provider models openai compatible
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`router.list_provider_models('openrouter') == ['model-a', 'model-b']`
- **位置**：`test_router.py:61-76` · 意图由函数名推断

#### 6. `test_resolve_effective_provider_auto`

- **意图**：覆盖: resolve effective provider auto
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`router.resolve_effective_provider('cursor') == 'cursor'; router.resolve_effective_provider('auto') == 'openrouter'`
- **位置**：`test_router.py:79-87` · 意图由函数名推断

#### 7. `test_provider_order_auto_uses_env_priority`

- **意图**：覆盖: provider order auto uses env priority
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`router._provider_order(None) == ['openrouter', 'ollama', 'cursor']`
- **位置**：`test_router.py:90-96` · 意图由函数名推断

#### 8. `test_provider_order_prefer_puts_choice_first`

- **意图**：覆盖: provider order prefer puts choice first
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`router._provider_order('ollama') == ['ollama', 'openrouter', 'cursor']; router._provider_order(None) == ['openrouter', 'ollama', 'cursor']`
- **位置**：`test_router.py:99-106` · 意图由函数名推断

#### 9. `test_format_messages_for_cursor_includes_latest_user`

- **意图**：覆盖: format messages for cursor includes lauser
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'System:' in prompt; 'User:\nhello' in prompt; prompt.endswith('Assistant:')`
- **位置**：`test_router.py:109-117` · 意图由函数名推断

#### 10. `test_chat_ollama_disables_thinking_by_default`

- **意图**：覆盖: chat ollama disables thinking by default
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`payload['think'] is False; payload['keep_alive'] == server.keep_alive; payload['options']['num_predict'] == server.num_predict; payload['options']['num_ctx'] == server.num_ctx`
- **位置**：`test_router.py:120-137` · 意图由函数名推断

#### 11. `test_chat_ollama_streaming_payload`

- **意图**：覆盖: chat ollama streaming payload
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`payload['stream'] is True; payload['think'] is False`
- **位置**：`test_router.py:140-148` · 意图由函数名推断

#### 12. `test_chat_openai_compatible_streaming`

- **意图**：覆盖: chat openai compatible streaming
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`text == '你好'; ''.join(seen) == '你好'; usage == {}; method == 'POST'; json['stream'] is True`
- **位置**：`test_router.py:151-211` · 意图由函数名推断

#### 13. `test_chat_auto_falls_back_when_ollama_times_out`

- **意图**：覆盖: chat auto falls back when ollama times out
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`reply == 'cloud reply'; router._ollama_slow is True; router.last_provider == 'openrouter'; router.last_model == config.OPENROUTER_MODEL`
- **位置**：`test_router.py:214-236` · 意图由函数名推断

#### 14. `test_chat_auto_skips_ollama_after_slow_mark`

- **意图**：覆盖: chat auto skips ollama after slow mark
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`reply == 'ok'; router.last_provider == 'openrouter'; router.last_model == config.OPENROUTER_MODEL`
- **位置**：`test_router.py:239-261` · 意图由函数名推断

#### 15. `test_chat_openai_raises_clear_error_on_missing_model`

- **意图**：覆盖: chat openai raises clear error on missing model
- **输入**：无外部夹具
- **方法**：mock + raises
- **校验**：`(隐式/副作用校验)`
- **位置**：`test_router.py:264-287` · 意图由函数名推断

#### 16. `test_chat_openrouter_raises_clear_error_on_missing_model`

- **意图**：覆盖: chat openrouter raises clear error on missing model
- **输入**：无外部夹具
- **方法**：mock + raises
- **校验**：`(隐式/副作用校验)`
- **位置**：`test_router.py:290-312` · 意图由函数名推断

#### 17. `test_chat_cursor_uses_cursor_sdk`

- **意图**：覆盖: chat cursor uses cursor sdk
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`reply == 'hello from cursor'`
- **位置**：`test_router.py:315-328` · 意图由函数名推断

#### 18. `test_chat_retries_ollama_after_cloud_failures_when_ollama_slow`

- **意图**：覆盖: chat retries ollama after cloud failures when ollama slow
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`reply == 'local ok'; router.last_provider == 'ollama'; router._ollama_slow is False`
- **位置**：`test_router.py:331-360` · 意图由函数名推断

#### 19. `test_chat_cursor_retries_before_fallback`

- **意图**：覆盖: chat cursor retries before fallback
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch + mock
- **校验**：`reply == 'ok after retry'; attempts['count'] == 3`
- **位置**：`test_router.py:363-380` · 意图由函数名推断

#### 20. `test_chat_falls_back_to_ollama_when_cursor_fails`

- **意图**：覆盖: chat falls back to ollama when cursor fails
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`reply == 'ollama fallback'; router.last_provider == 'ollama'`
- **位置**：`test_router.py:383-404` · 意图由函数名推断

#### 21. `test_format_model_hint_for_openai`

- **意图**：覆盖: format model hint for openai
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`router.format_model_hint('openai') == 'gpt-4o-mini'`
- **位置**：`test_router.py:407-413` · 意图由函数名推断

#### 22. `test_format_provider_hint`

- **意图**：覆盖: format provider hint
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`router.format_provider_hint('auto') == 'auto(ollama→openai→openrouter→cursor)'; router.format_provider_hint('openrouter') == 'openrouter(ollama→openai→cursor)'`
- **位置**：`test_router.py:416-423` · 意图由函数名推断

#### 23. `test_format_last_source`

- **意图**：覆盖: format last source
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`router.format_last_source() is None; router.format_last_source() == 'openrouter/anthropic/claude-sonnet-4'; router.format_last_source() == 'openrouter'`
- **位置**：`test_router.py:426-433` · 意图由函数名推断


## Memory

### `test_chatgpt_import.py`（23）

#### 1. `test_reconstruct_messages_chronological_order`

- **意图**：覆盖: reconstruct messages chronological order
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`[m.role for m in conv.messages] == ['user', 'assistant']; conv.messages[0].content.startswith('我喜欢用 Python')`
- **位置**：`test_chatgpt_import.py:78-81` · 意图由函数名推断

#### 2. `test_strip_cite_markers`

- **意图**：覆盖: strip cite markers
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`strip_cite_markers(raw) == '结论正确，可以继续。'`
- **位置**：`test_chatgpt_import.py:84-86` · 意图由函数名推断

#### 3. `test_skip_non_text_content_types`

- **意图**：覆盖: skip non text content types
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`[m.role for m in parsed.messages] == ['user']`
- **位置**：`test_chatgpt_import.py:89-93` · 意图由函数名推断

#### 4. `test_format_conversation_text_includes_title_and_roles`

- **意图**：覆盖: format conversation text includes title and roles
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'title: 职业规划' in text; 'user: 我喜欢用 Python 做数据分析' in text; 'assistant:' in text; '[2025-09-05]' in text`
- **位置**：`test_chatgpt_import.py:96-102` · 意图由函数名推断

#### 5. `test_format_conversation_text_includes_message_timestamps`

- **意图**：覆盖: format conversation text includes message timestamps
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'[2025-09-05] user:' in text; '[2025-09-05] assistant:' in text`
- **位置**：`test_chatgpt_import.py:105-109` · 意图由函数名推断

#### 6. `test_load_real_sample_file`

- **意图**：覆盖: load real sample file
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`len(conversations) == 100; conversations[0].title; conversations[0].messages`
- **位置**：`test_chatgpt_import.py:112-119` · 意图由函数名推断

#### 7. `test_import_chatgpt_saves_memories`

- **意图**：覆盖: import chatgpt saves memories
- **输入**：夹具: isolated_data, tmp_path
- **方法**：temp data
- **校验**：`summary.imported == 1; summary.saved_count == 1; get_memory_store().count() == before + 1; fact.created_at.startswith('2025-09-05'); fact.metadata.get('chatgpt_created_at', '').startswith('2025-09-05')`
- **位置**：`test_chatgpt_import.py:122-137` · 意图由函数名推断

#### 8. `test_import_chatgpt_skips_do_not_remember`

- **意图**：覆盖: import chatgpt skips do not remember
- **输入**：夹具: isolated_data, tmp_path
- **方法**：temp data
- **校验**：`summary.imported == 0; summary.skipped_do_not_remember == 1`
- **位置**：`test_chatgpt_import.py:140-152` · 意图由函数名推断

#### 9. `test_import_chatgpt_deduplicates_by_conversation_id`

- **意图**：覆盖: import chatgpt deduplicates by conversation id
- **输入**：夹具: isolated_data, tmp_path
- **方法**：temp data
- **校验**：`first.imported == 1; second.imported == 0; second.skipped_duplicate == 1`
- **位置**：`test_chatgpt_import.py:155-167` · 意图由函数名推断

#### 10. `test_import_chatgpt_force_reimports`

- **意图**：覆盖: import chatgpt force reimports
- **输入**：夹具: isolated_data, tmp_path
- **方法**：temp data
- **校验**：`forced.imported == 1; get_memory_store().count() == before + 2`
- **位置**：`test_chatgpt_import.py:170-182` · 意图由函数名推断

#### 11. `test_import_chatgpt_auto_saves_in_tty`

- **意图**：Default import saves without prompting even when stdin is a TTY.
- **输入**：夹具: isolated_data, tmp_path, monkeypatch
- **方法**：monkeypatch + temp data
- **校验**：`summary.imported == 1; summary.saved_count == 1; get_memory_store().count() == before + 1`
- **位置**：`test_chatgpt_import.py:185-204` · 有 docstring

#### 12. `test_import_chatgpt_reports_extracted_facts`

- **意图**：覆盖: import chatgpt reports extracted facts
- **输入**：夹具: isolated_data, tmp_path, capsys
- **方法**：stdout + temp data
- **校验**：`'→ 1 条记忆' in out; fact_text in out; '✓ 已保存 1 条' in out`
- **位置**：`test_chatgpt_import.py:207-221` · 意图由函数名推断

#### 13. `test_cli_import_chatgpt`

- **意图**：覆盖: cli import chatgpt
- **输入**：夹具: isolated_data, tmp_path, capsys
- **方法**：CLI/subprocess + stdout + temp data
- **校验**：`rc == 0; 'import-chatgpt' in out or 'memory ingest chatgpt' in out or '已写入' in out or ('files=' in out); 'imported=1' in out; '用户计划在2026年系统学习 Rust 语言' in out; get_memory_store().count() == before + 1`
- **位置**：`test_chatgpt_import.py:224-240` · 意图由函数名推断

#### 14. `test_cli_import_chatgpt_real_sample`

- **意图**：覆盖: cli import chatgpt real sample
- **输入**：夹具: isolated_data, capsys
- **方法**：CLI/subprocess + stdout + temp data
- **校验**：`rc == 0; 'conversations=100' in out; 'imported=100' in out; get_memory_store().count() == 100; 'dup=100' in out`
- **位置**：`test_chatgpt_import.py:243-263` · 意图由函数名推断

#### 15. `test_load_memories_file_array_shape`

- **意图**：覆盖: load memories file array shape
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`len(memories) == 1; memories[0].memory_id == 'mem_abc'`
- **位置**：`test_chatgpt_import.py:270-288` · 意图由函数名推断

#### 16. `test_detect_chatgpt_export_kind`

- **意图**：覆盖: detect chatgpt export kind
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`detect_chatgpt_export_kind([{'mapping': {}}]) == 'conversations'; detect_chatgpt_export_kind([{'content': 'foo', 'enabled': True}]) == 'memories'; detect_chatgpt_export_kind({'memory': [{'content': 'bar'}]}) == 'memories'`
- **位置**：`test_chatgpt_import.py:291-294` · 意图由函数名推断

#### 17. `test_import_chatgpt_memories_saves_directly`

- **意图**：覆盖: import chatgpt memories saves directly
- **输入**：夹具: isolated_data, tmp_path
- **方法**：temp data
- **校验**：`summary.memories_total == 2; summary.imported == 1; summary.saved_count == 1; summary.skipped_disabled == 1; get_memory_store().count() == before + 1`
- **位置**：`test_chatgpt_import.py:297-327` · 意图由函数名推断

#### 18. `test_import_chatgpt_memories_include_disabled`

- **意图**：覆盖: import chatgpt memories include disabled
- **输入**：夹具: isolated_data, tmp_path
- **方法**：temp data
- **校验**：`summary.imported == 1; summary.saved_count == 1`
- **位置**：`test_chatgpt_import.py:330-344` · 意图由函数名推断

#### 19. `test_import_chatgpt_memories_deduplicates`

- **意图**：覆盖: import chatgpt memories deduplicates
- **输入**：夹具: isolated_data, tmp_path
- **方法**：temp data
- **校验**：`first.imported == 1; second.imported == 0; second.skipped_duplicate == 1`
- **位置**：`test_chatgpt_import.py:347-363` · 意图由函数名推断

#### 20. `test_cli_import_chatgpt_memory_file`

- **意图**：覆盖: cli import chatgpt memory file
- **输入**：夹具: isolated_data, tmp_path, capsys
- **方法**：CLI/subprocess + stdout + temp data
- **校验**：`rc == 0; 'import-chatgpt' in out or 'memory ingest chatgpt' in out or '已写入' in out or ('files=' in out); 'memories=1' in out; get_memory_store().count() == before + 1`
- **位置**：`test_chatgpt_import.py:366-385` · 意图由函数名推断

#### 21. `test_import_chatgpt_files_multiple`

- **意图**：覆盖: import chatgpt files multiple
- **输入**：夹具: isolated_data, tmp_path
- **方法**：temp data
- **校验**：`summary.files_processed == 2; summary.imported == 2`
- **位置**：`test_chatgpt_import.py:388-409` · 意图由函数名推断

#### 22. `test_cli_import_chatgpt_with_file_flag`

- **意图**：覆盖: cli import chatgpt with file flag
- **输入**：夹具: isolated_data, tmp_path, capsys
- **方法**：CLI/subprocess + stdout + temp data
- **校验**：`rc == 0; 'imported=1' in out`
- **位置**：`test_chatgpt_import.py:412-427` · 意图由函数名推断

#### 23. `test_cli_import_chatgpt_file_force_reimports`

- **意图**：覆盖: cli import chatgpt file force reimports
- **输入**：夹具: isolated_data, tmp_path, capsys
- **方法**：CLI/subprocess + stdout + temp data
- **校验**：`rc == 0; get_memory_store().count() == before + 1; 'dup=1' in out; 'imported=1' in out; get_memory_store().count() == before + 2`
- **位置**：`test_chatgpt_import.py:430-454` · 意图由函数名推断


### `test_conversation_persist.py`（5）

#### 1. `test_append_message_writes_chatgpt_mapping`

- **意图**：覆盖: append message writes chatgpt mapping
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`path.is_file(); raw['conversation_id'] == sid; 'mapping' in raw; raw['current_node']; obj is not None`
- **位置**：`test_conversation_persist.py:19-45` · 意图由函数名推断

#### 2. `test_migrate_legacy_jsonl`

- **意图**：覆盖: migrate legacy jsonl
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`obj is not None; len(obj.messages) == 2; conversation_path(sid).is_file()`
- **位置**：`test_conversation_persist.py:48-63` · 意图由函数名推断

#### 3. `test_is_narrative_memory_rejects_keyword_soup`

- **意图**：覆盖: is narrative memory rejects keyword soup
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`not is_narrative_memory('总部；HUMAN；目标管理'); not is_narrative_memory('计划plan；任务拆解；skill使用'); is_narrative_memory('用户喜欢喝葡萄酒。'); is_narrative_memory('用户于 2026-03-20 决定采用 Mem0 作为记忆引擎。')`
- **位置**：`test_conversation_persist.py:66-70` · 意图由函数名推断

#### 4. `test_parse_extracted_memories_json`

- **意图**：覆盖: parse extracted memories json
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`len(memories) == 1; memories[0].text.startswith('用户喜欢'); memories[0].slots.get('object') == '葡萄酒'`
- **位置**：`test_conversation_persist.py:73-88` · 意图由函数名推断

#### 5. `test_parse_extracted_memories_rejects_soup`

- **意图**：覆盖: parse extracted memories rejects soup
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`parse_extracted_memories(reply) == []`
- **位置**：`test_conversation_persist.py:91-93` · 意图由函数名推断


### `test_exit_extract.py`（5）

#### 1. `test_extract_session_memories_from_persisted_conversation`

- **意图**：覆盖: extract session memories from persisted conversation
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`len(ids) >= 1; get_memory_store().count() >= before + 1`
- **位置**：`test_exit_extract.py:14-27` · 意图由函数名推断

#### 2. `test_extract_session_memories_skips_commands`

- **意图**：覆盖: extract session memories skips commands
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`extract_session_memories(session_id, interactive=False) == []; extract_session_memories(session_id2, interactive=False) == []`
- **位置**：`test_exit_extract.py:30-44` · 意图由函数名推断

#### 3. `test_ephemeral_session_skips_warm_summary`

- **意图**：Weather / news / identity probes stay in persist/, not Warm.
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`extract_session_memories(session_id, interactive=False) == []; build_session_summary_fact(session_id, [text]) is None`
- **位置**：`test_exit_extract.py:47-60` · 有 docstring

#### 4. `test_is_warm_worthy_session_gate`

- **意图**：覆盖: is warm worthy session gate
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`not is_warm_worthy_session(['天气怎么样?']); not is_warm_worthy_session(['AI最近有什么新闻吗?']); not is_warm_worthy_session(['我是谁']); is_warm_worthy_session(['我决定采用 Mem0 作为 Warm 记忆引擎'])`
- **位置**：`test_exit_extract.py:63-67` · 意图由函数名推断

#### 5. `test_schedule_session_memory_extract_spawns_detached_process`

- **意图**：覆盖: schedule session memory extract spawns detached process
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`popen.call_count >= 1; 'localagent.memory.exit_extract' in args[0]; args[0][-1] == 's-bg'; kwargs['stdin'] is subprocess.DEVNULL; kwargs['start_new_session'] is True`
- **位置**：`test_exit_extract.py:70-83` · 意图由函数名推断


### `test_memory_backend.py`（20）

#### 1. `test_default_bank_id_isolated_when_data_dir_override`

- **意图**：覆盖: default bank id isolated when data dir override
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`profile.startswith('la-'); profile == cfg.default_bank_id()`
- **位置**：`test_memory_backend.py:31-37` · 意图由函数名推断

#### 2. `test_default_bank_id_default_profile_without_override`

- **意图**：覆盖: default bank id default profile without override
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`cfg.memory_user_id() == 'localagent'; cfg.default_bank_id() == 'localagent'`
- **位置**：`test_memory_backend.py:40-45` · 意图由函数名推断

#### 3. `test_parse_add_ids_from_dict`

- **意图**：覆盖: parse add ids from dict
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_parse_add_ids({'results': [{'id': 'a'}, {'id': 'b'}]}) == ['a', 'b']; _parse_add_ids({'id': 'single'}) == ['single']; _parse_add_ids({'success': True, 'items_count': 1}) == []`
- **位置**：`test_memory_backend.py:48-51` · 意图由函数名推断

#### 4. `test_mem0_recall_merges_local_only_registry`

- **意图**：Mem0 hits must not hide JSON/ingest memories that were never indexed.
- **输入**：夹具: isolated_data
- **方法**：mock + temp data
- **校验**：`legacy is not None; any(('村上春树' in text for text in texts)); any(('Mem0' in text for text in texts))`
- **位置**：`test_memory_backend.py:54-83` · 有 docstring

#### 5. `test_is_engine_indexed`

- **意图**：覆盖: is engine indexed
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_is_engine_indexed(MemoryFact(id='1', text='x', source_file='', section_heading='', created_at='', metadata={'backend': 'mem0'})); _is_engine_indexed(MemoryFact(id='1', text='x', source_file='', section_heading='', created_at='', metadata={'mem0_id': 'abc'})); not _is_engine_indexed(MemoryFact(id='1', text='x', source_file='', section_heading='', created_at='', metadata={'backend': 'json'}))`
- **位置**：`test_memory_backend.py:86-118` · 意图由函数名推断

#### 6. `test_is_mem0_retain_error`

- **意图**：覆盖: is mem0 retain error
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_is_mem0_retain_error(Exception('Connection timeout')); _is_mem0_retain_error(Exception('embedding failed')); not _is_mem0_retain_error(ValueError('bad input'))`
- **位置**：`test_memory_backend.py:121-124` · 意图由函数名推断

#### 7. `test_mem0_retain_falls_back_to_json_on_error`

- **意图**：覆盖: mem0 retain falls back to json on error
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + mock + temp data
- **校验**：`fact_id; fact is not None; 'mem0_retain_failed' in fact.metadata`
- **位置**：`test_memory_backend.py:127-138` · 意图由函数名推断

#### 8. `test_mem0_retain_batch_continues_after_error`

- **意图**：覆盖: mem0 retain batch continues after error
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + mock + temp data
- **校验**：`len(ids) == 2`
- **位置**：`test_memory_backend.py:141-159` · 意图由函数名推断

#### 9. `test_save_facts_survives_mem0_retain_failure`

- **意图**：覆盖: save facts survives mem0 retain failure
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + mock + temp data
- **校验**：`len(ids) == 1`
- **位置**：`test_memory_backend.py:162-174` · 意图由函数名推断

#### 10. `test_json_backend_forced`

- **意图**：覆盖: json backend forced
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + temp data
- **校验**：`backend.backend_name() == 'json'`
- **位置**：`test_memory_backend.py:177-181` · 意图由函数名推断

#### 11. `test_resolve_store_fact_by_external_id`

- **意图**：覆盖: resolve store fact by external id
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`fact is not None; found is not None; found.id == fact_id`
- **位置**：`test_memory_backend.py:184-203` · 意图由函数名推断

#### 12. `test_merge_recall_hit_prefers_registry`

- **意图**：覆盖: merge recall hit prefers registry
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`hit['id'] == 'mem-1'; '采用 Mem0' in hit['text'] or hit['text']`
- **位置**：`test_memory_backend.py:206-223` · 意图由函数名推断

#### 13. `test_dedupe_recall_hits`

- **意图**：覆盖: dedupe recall hits
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`[h['id'] for h in merged] == ['a', 'b']`
- **位置**：`test_memory_backend.py:226-234` · 意图由函数名推断

#### 14. `test_json_backend_recall`

- **意图**：覆盖: json backend recall
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`hits; any(('Mem0' in h['text'] for h in hits))`
- **位置**：`test_memory_backend.py:237-245` · 意图由函数名推断

#### 15. `test_ollama_openai_base_url`

- **意图**：覆盖: ollama openai base url
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_ollama_openai_base_url('http://localhost:11434') == 'http://localhost:11434/v1'; _ollama_openai_base_url('http://localhost:11434/v1') == 'http://localhost:11434/v1'`
- **位置**：`test_memory_backend.py:248-250` · 意图由函数名推断

#### 16. `test_resolve_mem0_llm_prefers_ollama_when_available`

- **意图**：覆盖: resolve mem0 llm prefers ollama when available
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + mock + temp data
- **校验**：`settings['source_provider'] == 'ollama'; settings['model'] == 'qwen3.5:4b'`
- **位置**：`test_memory_backend.py:253-262` · 意图由函数名推断

#### 17. `test_resolve_mem0_embedder_uses_ollama_embed_model`

- **意图**：覆盖: resolve mem0 embedder uses ollama embed model
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + mock + temp data
- **校验**：`settings['source_provider'] == 'ollama'; settings['model'].startswith('bge-m3'); settings['embedding_dims'] == 1024`
- **位置**：`test_memory_backend.py:265-278` · 意图由函数名推断

#### 18. `test_mem0_telemetry_disabled_by_default`

- **意图**：覆盖: mem0 telemetry disabled by default
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`os.environ.get('MEM0_TELEMETRY') == 'False'; os.environ.get('MEM0_TELEMETRY') == 'True'`
- **位置**：`test_memory_backend.py:281-288` · 意图由函数名推断

#### 19. `test_mem0_backend_close_releases_qdrant_client`

- **意图**：覆盖: mem0 backend close releases qdrant client
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`backend._memory is None`
- **位置**：`test_memory_backend.py:291-302` · 意图由函数名推断

#### 20. `test_shutdown_memory_backend_closes_active_backend`

- **意图**：覆盖: shutdown memory backend closes active backend
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch + mock
- **校验**：`backend_mod._backend is None`
- **位置**：`test_memory_backend.py:305-314` · 意图由函数名推断


### `test_memory_enrich.py`（6）

#### 1. `test_enrich_heuristic_preserves_leading_year`

- **意图**：覆盖: enrich heuristic preserves leading year
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`result.title.startswith('2026年3月')`
- **位置**：`test_memory_enrich.py:9-12` · 意图由函数名推断

#### 2. `test_enrich_heuristic_generates_title_tags_summary`

- **意图**：覆盖: enrich heuristic generates title tags summary
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`result.title; 'Hindsight' in result.summary or 'Hindsight' in result.searchable_text; '技术' in result.tags or '决策' in result.tags; result.memory_type in ('fact', 'preference', 'plan')`
- **位置**：`test_memory_enrich.py:15-21` · 意图由函数名推断

#### 3. `test_enrich_heuristic_summarizes_long_text`

- **意图**：覆盖: enrich heuristic summarizes long text
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`len(result.summary) <= 210; result.searchable_text`
- **位置**：`test_memory_enrich.py:24-28` · 意图由函数名推断

#### 4. `test_format_memory_hit_readable_card`

- **意图**：覆盖: format memory hit readable card
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'### 1. 采用 Hindsight' in rendered; '相关度 0.82' in rendered; '#技术' in rendered; 'Hindsight' in rendered; 'id: abc12345' in rendered`
- **位置**：`test_memory_enrich.py:31-52` · 意图由函数名推断

#### 5. `test_format_memory_hits_header`

- **意图**：覆盖: format memory hits header
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'找到 1 条相关记忆' in rendered; '查询: 测试' in rendered`
- **位置**：`test_memory_enrich.py:55-68` · 意图由函数名推断

#### 6. `test_enrich_memory_fallback_for_empty`

- **意图**：覆盖: enrich memory fallback for empty
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`result.title == '空记忆'`
- **位置**：`test_memory_enrich.py:71-73` · 意图由函数名推断


### `test_memory_query.py`（9）

#### 1. `test_query_memories_semantic_match`

- **意图**：覆盖: query memories semantic match
- **输入**：无外部夹具
- **方法**：CLI/subprocess
- **校验**：`hits; any(('Hindsight' in hit['text'] for hit in hits))`
- **位置**：`test_memory_query.py:25-29` · 意图由函数名推断

#### 2. `test_query_memories_filter_by_tag`

- **意图**：覆盖: query memories filter by tag
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`len(hits) == 1; '深色主题' in hits[0]['text']`
- **位置**：`test_memory_query.py:32-38` · 意图由函数名推断

#### 3. `test_query_memories_filter_by_time_range`

- **意图**：覆盖: query memories filter by time range
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`len(hits) == 1; '2026年' in hits[0]['text']`
- **位置**：`test_memory_query.py:41-47` · 意图由函数名推断

#### 4. `test_query_memories_sort_oldest`

- **意图**：覆盖: query memories sort oldest
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`len(hits) >= 2; hits[0]['created_at'] <= hits[-1]['created_at']`
- **位置**：`test_memory_query.py:50-56` · 意图由函数名推断

#### 5. `test_list_memory_tags`

- **意图**：覆盖: list memory tags
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`tag_map.get('工作', 0) >= 2; tag_map.get('技术', 0) >= 1`
- **位置**：`test_memory_query.py:59-66` · 意图由函数名推断

#### 6. `test_cli_memories_browse`

- **意图**：覆盖: cli memories browse
- **输入**：夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; '记忆库共' in out; 'Hindsight' in out`
- **位置**：`test_memory_query.py:69-75` · 意图由函数名推断

#### 7. `test_cli_memories_semantic_query`

- **意图**：覆盖: cli memories semantic query
- **输入**：夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; '积雪' in out or '诗歌' in out`
- **位置**：`test_memory_query.py:78-83` · 意图由函数名推断

#### 8. `test_cli_memories_list_tags`

- **意图**：覆盖: cli memories list tags
- **输入**：夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; '偏好' in out`
- **位置**：`test_memory_query.py:86-91` · 意图由函数名推断

#### 9. `test_cli_memories_json_output`

- **意图**：覆盖: cli memories json output
- **输入**：夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; isinstance(data, list); data`
- **位置**：`test_memory_query.py:94-102` · 意图由函数名推断


### `test_memory_recall_priority.py`（10）

#### 1. `test_lexical_overlap_prefers_residence_fact_over_diary_noise`

- **意图**：覆盖: lexical overlap prefers residence fact over diary noise
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_lexical_overlap_score(query, fact) > _lexical_overlap_score(query, noise)`
- **位置**：`test_memory_recall_priority.py:19-26` · 意图由函数名推断

#### 2. `test_scoped_recall_ranks_recent_residence_first`

- **意图**：覆盖: scoped recall ranks recent residence first
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`hits; '深圳' in hits[0]['text']; '北京' not in hits[0]['text']`
- **位置**：`test_memory_recall_priority.py:29-72` · 意图由函数名推断

#### 3. `test_rewrite_location_query`

- **意图**：覆盖: rewrite location query
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'居住' in _rewrite_personal_memory_query('你知道我住在哪里吗?')`
- **位置**：`test_memory_recall_priority.py:75-76` · 意图由函数名推断

#### 4. `test_prefetch_personal_context_for_location_question`

- **意图**：覆盖: prefetch personal context for location question
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`ctx; '已预加载' in ctx; search.call_count >= 1; any(('居住' in str(call) for call in search.call_args_list))`
- **位置**：`test_memory_recall_priority.py:79-88` · 意图由函数名推断

#### 5. `test_explicit_remember_writes_memory_and_pins_profile`

- **意图**：覆盖: explicit remember writes memory and pins profile
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`'已记住' in result.response; result.tool_calls; result.tool_calls[0]['name'] == 'retain_memory'; hits; any(('深圳' in h['text'] for h in hits))`
- **位置**：`test_memory_recall_priority.py:91-102` · 意图由函数名推断

#### 6. `test_scoped_recall_bm25_finds_english_entity_fact`

- **意图**：覆盖: scoped recall bm25 finds english entity fact
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`hits; any(('adoption agencies' in h['text'] for h in hits)); any(((h.get('metadata') or {}).get('dia_id') == 'D2:8' for h in hits))`
- **位置**：`test_memory_recall_priority.py:105-126` · 意图由函数名推断

#### 7. `test_retain_memory_tool`

- **意图**：覆盖: retain memory tool
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`'已记住' in msg; any(('美式咖啡' in h['text'] for h in hits))`
- **位置**：`test_memory_recall_priority.py:129-133` · 意图由函数名推断

#### 8. `test_expand_recall_queries_strips_wh_words`

- **意图**：覆盖: expand recall queries strips wh words
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`variants[0] == 'What did Caroline research?'; any(('research' in v.lower() and 'what' not in v.lower().split() for v in variants))`
- **位置**：`test_memory_recall_priority.py:136-141` · 意图由函数名推断

#### 9. `test_extract_occurred_at_english_locomo_date`

- **意图**：覆盖: extract occurred at english locomo date
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`extract_occurred_at('1:56 pm on 8 May, 2023') == '2023-05-08'; extract_occurred_at('May 8, 2023') == '2023-05-08'; effective.startswith('2023-06-09')`
- **位置**：`test_memory_recall_priority.py:144-153` · 意图由函数名推断

#### 10. `test_rrf_fuse_hits_prefers_overlap`

- **意图**：覆盖: rrf fuse hits prefers overlap
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`fused[0]['id'] == 'b'; fused[0]['rrf_score'] > fused[1]['rrf_score']`
- **位置**：`test_memory_recall_priority.py:156-166` · 意图由函数名推断


### `test_memory_store.py`（1）

#### 1. `test_retain_from_section_respects_created_at_override`

- **意图**：覆盖: retain from section respects created at override
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`fact is not None; fact.metadata['occurred_at'] == '2024-01-01'; fact.metadata['recorded_at'] == '2024-06-15T10:00:00'; fact.created_at == '2024-01-01'; 'created_at' not in fact.metadata`
- **位置**：`test_memory_store.py:8-21` · 意图由函数名推断


### `test_memory_temporal.py`（7）

#### 1. `test_extract_occurred_at_cjk`

- **意图**：覆盖: extract occurred at cjk
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`extract_occurred_at('2024年6月15日决定跳槽') == '2024-06-15'; extract_occurred_at('2024 年先入职 A 公司') == '2024-01-01'; extract_occurred_at('2025年3月开始新项目') == '2025-03-01'; extract_occurred_at('2026年7月决定使用 Hindsight') == '2026-07-01'`
- **位置**：`test_memory_temporal.py:16-20` · 意图由函数名推断

#### 2. `test_extract_occurred_at_isoish`

- **意图**：覆盖: extract occurred at isoish
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`extract_occurred_at('事件发生于 2024-06-15') == '2024-06-15'; extract_occurred_at('更新于 2024/06/15') == '2024-06-15'`
- **位置**：`test_memory_temporal.py:23-25` · 意图由函数名推断

#### 3. `test_effective_memory_time_priority`

- **意图**：覆盖: effective memory time priority
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`effective_memory_time(occurred_at='2024-01-01', recorded_at='2025-01-01', indexed_at='2026-01-01') == '2024-01-01'; effective_memory_time(recorded_at='2025-01-01', indexed_at='2026-01-01') == '2025-01-01'; effective_memory_time(indexed_at='2026-01-01') == '2026-01-01'`
- **位置**：`test_memory_temporal.py:28-38` · 意图由函数名推断

#### 4. `test_retain_from_section_sets_occurred_and_recorded`

- **意图**：覆盖: retain from section sets occurred and recorded
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`fact is not None; fact.metadata['occurred_at'] == '2024-01-01'; fact.metadata['recorded_at'] == '2024-06-15T10:00:00'; fact.metadata['indexed_at']; fact.created_at == '2024-01-01'`
- **位置**：`test_memory_temporal.py:41-56` · 意图由函数名推断

#### 5. `test_retain_from_section_legacy_created_at_maps_to_recorded`

- **意图**：覆盖: retain from section legacy created at maps to recorded
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`fact is not None; fact.metadata['recorded_at'] == '2023-05-01T12:00:00'; fact.created_at == '2023-05-01T12:00:00'`
- **位置**：`test_memory_temporal.py:59-70` · 意图由函数名推断

#### 6. `test_memory_effective_time_from_metadata`

- **意图**：覆盖: memory effective time from metadata
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`effective == '2022-01-01'`
- **位置**：`test_memory_temporal.py:73-82` · 意图由函数名推断

#### 7. `test_resolve_memory_times_extracts_from_text`

- **意图**：覆盖: resolve memory times extracts from text
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`times['occurred_at'] == '2026-07-01'; times['recorded_at'] == '2026-07-10T08:00:00'; times['effective_at'] == '2026-07-01'; datetime.fromisoformat(times['indexed_at'])`
- **位置**：`test_memory_temporal.py:85-93` · 意图由函数名推断


### `test_phase_a_recall.py`（8）

#### 1. `test_decompose_keeps_simple_query`

- **意图**：覆盖: decompose keeps simple query
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`decompose_recall_query(q) == [q]`
- **位置**：`test_phase_a_recall.py:12-15` · 意图由函数名推断

#### 2. `test_decompose_splits_both_and`

- **意图**：覆盖: decompose splits both and
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`parts[0] == q; len(parts) >= 2; 'caroline' in joined; 'melanie' in joined or 'painting' in joined`
- **位置**：`test_phase_a_recall.py:18-27` · 意图由函数名推断

#### 3. `test_decompose_disabled_returns_original`

- **意图**：覆盖: decompose disabled returns original
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`decompose_recall_query(q) == [q]`
- **位置**：`test_phase_a_recall.py:30-33` · 意图由函数名推断

#### 4. `test_extract_entities_finds_quoted_and_names`

- **意图**：覆盖: extract entities finds quoted and names
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'caroline' in lower or any(('caroline' in e.lower() for e in ents)); any(('blue harbor' in e.lower() for e in ents)) or 'seattle' in lower`
- **位置**：`test_phase_a_recall.py:36-40` · 意图由函数名推断

#### 5. `test_entity_overlap_score`

- **意图**：覆盖: entity overlap score
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`score >= 0.5`
- **位置**：`test_phase_a_recall.py:43-49` · 意图由函数名推断

#### 6. `test_enrich_heuristic_includes_entities`

- **意图**：覆盖: enrich heuristic includes entities
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`enriched.entities; 'entities' in enriched.to_metadata()`
- **位置**：`test_phase_a_recall.py:52-55` · 意图由函数名推断

#### 7. `test_finalize_hybrid_rank_entity_boost`

- **意图**：覆盖: finalize hybrid rank entity boost
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`ranked; ranked[0]['id'] == 'target'; float(ranked[0].get('entity_score') or 0.0) > float(ranked[1].get('entity_score') or 0.0)`
- **位置**：`test_phase_a_recall.py:58-87` · 意图由函数名推断

#### 8. `test_rerank_off_preserves_order`

- **意图**：覆盖: rerank off preserves order
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`[h['id'] for h in out] == ['a', 'b']`
- **位置**：`test_phase_a_recall.py:90-97` · 意图由函数名推断


### `test_phase_b_summary_tasks.py`（4）

#### 1. `test_heuristic_summary_truncates`

- **意图**：覆盖: heuristic summary truncates
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`len(summary) <= 80; '第一句' in summary`
- **位置**：`test_phase_b_summary_tasks.py:20-24` · 意图由函数名推断

#### 2. `test_build_document_summary_facts_for_long_text`

- **意图**：覆盖: build document summary facts for long text
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`facts; facts[0]['metadata']['memory_kind'] == 'summary'; '文档摘要' in facts[0]['text']`
- **位置**：`test_phase_b_summary_tasks.py:27-35` · 意图由函数名推断

#### 3. `test_add_file_writes_warm_summary_for_long_doc`

- **意图**：覆盖: add file writes warm summary for long doc
- **输入**：夹具: tmp_path, monkeypatch
- **方法**：monkeypatch + temp data
- **校验**：`target.name == 'long-notes.md'; result.status == IngestStatus.NEW; result.knowledge_chunk_count >= 1; result.memory_fact_count >= 1; get_memory_store().count() > before`
- **位置**：`test_phase_b_summary_tasks.py:38-56` · 意图由函数名推断

#### 4. `test_create_memorize_session_task`

- **意图**：覆盖: create memorize session task
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`task.type == 'memorize_session'; task.source_path == 's-demo'; task.status.value == 'queued'; any((t.id == task.id for t in listed))`
- **位置**：`test_phase_b_summary_tasks.py:59-65` · 意图由函数名推断


### `test_phase_c_reflect_consolidate.py`（6）

#### 1. `test_parse_hop_decision_ready`

- **意图**：覆盖: parse hop decision ready
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`ready is True; queries == []`
- **位置**：`test_phase_c_reflect_consolidate.py:17-20` · 意图由函数名推断

#### 2. `test_parse_hop_decision_need`

- **意图**：覆盖: parse hop decision need
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`ready is False; queries == ['Caroline painting', 'Melanie trip']`
- **位置**：`test_phase_c_reflect_consolidate.py:23-28` · 意图由函数名推断

#### 3. `test_reflect_with_hops_followup`

- **意图**：覆盖: reflect with hops followup
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch + mock
- **校验**：`out == 'answer:2'; backend.recall.call_count == 2`
- **位置**：`test_phase_c_reflect_consolidate.py:31-62` · 意图由函数名推断

#### 4. `test_parse_consolidation_action`

- **意图**：覆盖: parse consolidation action
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`action.op == 'UPDATE'; action.target_id == 'abc'; '深圳' in action.text`
- **位置**：`test_phase_c_reflect_consolidate.py:65-72` · 意图由函数名推断

#### 5. `test_apply_update_replaces_fact`

- **意图**：覆盖: apply update replaces fact
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + temp data
- **校验**：`old_id; old_id in report.deleted_ids; report.updated_ids; any(('深圳' in t for t in texts)); not any((t == '用户居住在北京' for t in texts))`
- **位置**：`test_phase_c_reflect_consolidate.py:75-99` · 意图由函数名推断

#### 6. `test_consolidate_disabled_just_adds`

- **意图**：覆盖: consolidate disabled just adds
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + temp data
- **校验**：`len(report.retained_ids) == 1; report.actions[0].op == 'ADD'`
- **位置**：`test_phase_c_reflect_consolidate.py:102-110` · 意图由函数名推断


### `test_profile_pin.py`（14）

#### 1. `test_pin_location_occupation_family_preference`

- **意图**：覆盖: pin location occupation family preference
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`profile.preferences.get('居住地') == '深圳'; profile.preferences.get('家庭') == '有2个儿子'; profile.preferences.get('职业') == '开发工程师'; profile.current_status == '开发工程师'; profile.preferences.get('喜欢') == '喝美式咖啡'`
- **位置**：`test_profile_pin.py:19-30` · 意图由函数名推断

#### 2. `test_pin_name_and_reject_role_as_name`

- **意图**：覆盖: pin name and reject role as name
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`profile.name == ''; profile.preferences.get('职业') == '开发工程师'; profile.name == '林晓'`
- **位置**：`test_profile_pin.py:33-41` · 意图由函数名推断

#### 3. `test_pin_alternate_location_phrases`

- **意图**：覆盖: pin alternate location phrases
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`load_core_profile().preferences.get('居住地') == '广州'; load_core_profile().preferences.get('居住地') == '杭州'; load_core_profile().preferences.get('居住地') == '深圳'; load_core_profile().preferences.get('居住地') == '成都高新区'`
- **位置**：`test_profile_pin.py:44-55` · 意图由函数名推断

#### 4. `test_save_facts_pins_profile`

- **意图**：覆盖: save facts pins profile
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`profile.preferences.get('居住地') == '深圳'; profile.preferences.get('家庭') == '有2个儿子'`
- **位置**：`test_profile_pin.py:58-62` · 意图由函数名推断

#### 5. `test_cmd_add_pins_profile`

- **意图**：覆盖: cmd add pins profile
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`rc == 0; profile.preferences.get('居住地') == '深圳'; profile.preferences.get('职业') == '软件工程师'`
- **位置**：`test_profile_pin.py:65-70` · 意图由函数名推断

#### 6. `test_parse_profile_updates_reply`

- **意图**：覆盖: parse profile updates reply
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`len(updates) == 1; updates[0]['value'] == '深圳'; wrapped[0]['field'] == 'name'`
- **位置**：`test_profile_pin.py:73-83` · 意图由函数名推断

#### 7. `test_apply_profile_updates_and_life_anchor`

- **意图**：覆盖: apply profile updates and life anchor
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`apply_profile_updates([{'field': 'name', 'value': '林晓', 'confidence': 0.9}, {'field': 'preference', 'key': '居住地', 'value': '深圳', 'confidence; profile.name == '林晓'; profile.preferences['居住地'] == '深圳'; profile.preferences['家庭'] == '有两个儿子'; profile.preferences['职业'] == '开发工程师'`
- **位置**：`test_profile_pin.py:86-112` · 意图由函数名推断

#### 8. `test_llm_pin_path`

- **意图**：覆盖: llm pin path
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + temp data
- **校验**：`profile.preferences.get('居住地') == '鹏城'; profile.preferences.get('家庭') == '有两个儿子'; profile.preferences.get('职业') == '写代码的开发者'`
- **位置**：`test_profile_pin.py:115-131` · 意图由函数名推断

#### 9. `test_llm_failure_falls_back_to_regex`

- **意图**：覆盖: llm failure falls back to regex
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + temp data
- **校验**：`load_core_profile().preferences.get('居住地') == '深圳'`
- **位置**：`test_profile_pin.py:134-140` · 意图由函数名推断

#### 10. `test_regex_helper_still_works`

- **意图**：覆盖: regex helper still works
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`pin_fact_with_regex('我叫王芳'); load_core_profile().name == '王芳'`
- **位置**：`test_profile_pin.py:143-145` · 意图由函数名推断

#### 11. `test_pin_location_from_utterance`

- **意图**：覆盖: pin location from utterance
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`pin_location_from_utterance('深圳') == '深圳'; load_core_profile().preferences.get('居住地') == '深圳'`
- **位置**：`test_profile_pin.py:148-152` · 意图由函数名推断

#### 12. `test_default_core_profile_does_not_wipe_preferences`

- **意图**：覆盖: default core profile does not wipe preferences
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`profile.preferences.get('居住地') == '深圳'`
- **位置**：`test_profile_pin.py:155-160` · 意图由函数名推断

#### 13. `test_save_core_profile_merges_existing_preferences`

- **意图**：覆盖: save core profile merges existing preferences
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`profile.preferences.get('居住地') == '深圳'; profile.preferences.get('职业') == '工程师'`
- **位置**：`test_profile_pin.py:163-171` · 意图由函数名推断

#### 14. `test_resolve_home_location_from_memory`

- **意图**：覆盖: resolve home location from memory
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`home_location() == ''; resolve_home_location() == '深圳'; home_location() == '深圳'`
- **位置**：`test_profile_pin.py:174-208` · 意图由函数名推断


### `test_session_recall.py`（1）

#### 1. `test_is_session_recall_query`

- **意图**：覆盖: is session recall query
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`is_session_recall_query('今天的聊天记录') is True; is_session_recall_query('我今天问了啥?') is True; is_session_recall_query('最近有什么新闻?') is False`
- **位置**：`test_session_recall.py:6-9` · 意图由函数名推断


### `test_temporal_intent_recall.py`（11）

#### 1. `test_parse_when_event_locomo_style`

- **意图**：覆盖: parse when event locomo style
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`intent.intent_kind == 'when_event'; intent.anchor_date is None; intent.prefers_event_neighbors`
- **位置**：`test_temporal_intent_recall.py:16-20` · 意图由函数名推断

#### 2. `test_parse_duration`

- **意图**：覆盖: parse duration
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`intent.intent_kind == 'duration'; intent.prefers_event_neighbors`
- **位置**：`test_temporal_intent_recall.py:23-26` · 意图由函数名推断

#### 3. `test_parse_as_of_now`

- **意图**：覆盖: parse as of now
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`intent.intent_kind == 'as_of_now'; intent.raises_temporal_weight; intent.anchor_date is not None`
- **位置**：`test_temporal_intent_recall.py:29-33` · 意图由函数名推断

#### 4. `test_parse_english_last_week_with_reference_date`

- **意图**：覆盖: parse english last week with reference date
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`intent.intent_kind == 'range'; intent.scope_start == '2023-06-05'; intent.scope_end == '2023-06-11'; intent.raises_temporal_weight`
- **位置**：`test_temporal_intent_recall.py:36-44` · 意图由函数名推断

#### 5. `test_parse_english_month_year`

- **意图**：覆盖: parse english month year
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`intent.intent_kind == 'range'; intent.scope_start == '2023-05-01'; intent.scope_end == '2023-05-31'`
- **位置**：`test_temporal_intent_recall.py:47-51` · 意图由函数名推断

#### 6. `test_explicit_year_beats_when_wording`

- **意图**：覆盖: explicit year beats when wording
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`intent.intent_kind == 'range'; intent.scope_start == '2023-01-01'`
- **位置**：`test_temporal_intent_recall.py:54-57` · 意图由函数名推断

#### 7. `test_scope_alignment_in_near_out`

- **意图**：覆盖: scope alignment in near out
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_scope_alignment_score('2023-05-08', intent) == 1.0; _scope_alignment_score('2023-06-10', intent) == 0.5; _scope_alignment_score('2024-01-01', intent) == 0.15`
- **位置**：`test_temporal_intent_recall.py:60-69` · 意图由函数名推断

#### 8. `test_intent_temporal_score_prefers_in_window`

- **意图**：覆盖: intent temporal score prefers in window
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`in_window > out_window`
- **位置**：`test_temporal_intent_recall.py:72-89` · 意图由函数名推断

#### 9. `test_hybrid_weights_raise_for_range`

- **意图**：覆盖: hybrid weights raise for range
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`range_w[3] > when_w[3]; range_w[3] > none_w[3]`
- **位置**：`test_temporal_intent_recall.py:92-97` · 意图由函数名推断

#### 10. `test_scoped_recall_prefers_in_scope_memory`

- **意图**：覆盖: scoped recall prefers in scope memory
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`hits; hits[0]['anchor']['intent_kind'] == 'range'; '产品路线' in hits[0]['text']; hits[0]['temporal_score'] >= hits[-1]['temporal_score']`
- **位置**：`test_temporal_intent_recall.py:100-122` · 意图由函数名推断

#### 11. `test_finalize_hybrid_rank_attaches_when_event_intent`

- **意图**：覆盖: finalize hybrid rank attaches when event intent
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`ranked; ranked[0]['anchor']['intent_kind'] == 'when_event'; 'Caroline' in ranked[0]['text']`
- **位置**：`test_temporal_intent_recall.py:125-151` · 意图由函数名推断


## Agent/Tools

### `test_agent_runtime.py`（53）

#### 1. `test_answer_stream_gate_emits_prose`

- **意图**：覆盖: answer stream gate emits prose
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`gate is not None; ''.join(seen) == '你好，世界'`
- **位置**：`test_agent_runtime.py:24-30` · 意图由函数名推断

#### 2. `test_answer_stream_gate_mutes_tool_fence`

- **意图**：覆盖: answer stream gate mutes tool fence
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`gate is not None; seen == []`
- **位置**：`test_agent_runtime.py:33-39` · 意图由函数名推断

#### 3. `test_answer_stream_gate_mutes_bare_json_tool`

- **意图**：覆盖: answer stream gate mutes bare json tool
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`gate is not None; seen == []`
- **位置**：`test_agent_runtime.py:42-47` · 意图由函数名推断

#### 4. `test_answer_stream_gate_none`

- **意图**：覆盖: answer stream gate none
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_make_answer_stream_gate(None) is None`
- **位置**：`test_agent_runtime.py:50-51` · 意图由函数名推断

#### 5. `test_run_agent_turn_streams_final_answer_not_tool_json`

- **意图**：覆盖: run agent turn streams final answer not tool json
- **输入**：夹具: isolated_data
- **方法**：mock + temp data
- **校验**：`result.response == answer; ''.join(seen) == answer; '```tool' not in ''.join(seen); isolated_data['router'].chat.call_count == 2`
- **位置**：`test_agent_runtime.py:54-84` · 意图由函数名推断

#### 6. `test_parse_tool_call_accepts_tool_fence`

- **意图**：覆盖: parse tool call accepts tool fence
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_parse_tool_call(text) == {'name': 'search_memory', 'arguments': {'query': '我是谁'}}`
- **位置**：`test_agent_runtime.py:87-92` · 意图由函数名推断

#### 7. `test_parse_tool_call_accepts_json_fence`

- **意图**：覆盖: parse tool call accepts json fence
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_parse_tool_call(text) == {'name': 'search_knowledge', 'arguments': {'query': '几年前的关注点'}}`
- **位置**：`test_agent_runtime.py:95-100` · 意图由函数名推断

#### 8. `test_parse_tool_call_accepts_bare_json`

- **意图**：覆盖: parse tool call accepts bare json
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_parse_tool_call(text) == {'name': 'web_search', 'arguments': {'query': '今日新闻'}}`
- **位置**：`test_agent_runtime.py:103-108` · 意图由函数名推断

#### 9. `test_parse_tool_call_rejects_unknown_tool`

- **意图**：覆盖: parse tool call rejects unknown tool
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_parse_tool_call('{"name": "delete_everything", "arguments": {}}') is None`
- **位置**：`test_agent_runtime.py:111-112` · 意图由函数名推断

#### 10. `test_parse_tool_call_accepts_xml_format`

- **意图**：覆盖: parse tool call accepts xml format
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_parse_tool_call(text) == {'name': 'search_memory', 'arguments': {'query': 'Memory System 研究 去年'}}`
- **位置**：`test_agent_runtime.py:115-125` · 意图由函数名推断

#### 11. `test_strip_tool_blocks`

- **意图**：覆盖: strip tool blocks
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'query_memories' not in _strip_tool_blocks(text); '先说一段' in _strip_tool_blocks(text)`
- **位置**：`test_agent_runtime.py:128-131` · 意图由函数名推断

#### 12. `test_strip_tool_blocks_removes_xml_tool_call`

- **意图**：覆盖: strip tool blocks removes xml tool call
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_strip_tool_blocks(text) == '让我搜索。'`
- **位置**：`test_agent_runtime.py:134-141` · 意图由函数名推断

#### 13. `test_looks_like_tool_attempt_detects_truncated_fence`

- **意图**：覆盖: looks like tool attempt detects truncated fence
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_looks_like_tool_attempt(text); _parse_tool_call(text) is None; _strip_tool_blocks(text) == ''`
- **位置**：`test_agent_runtime.py:144-150` · 意图由函数名推断

#### 14. `test_run_agent_turn_retries_truncated_tool_call`

- **意图**：覆盖: run agent turn retries truncated tool call
- **输入**：夹具: isolated_data
- **方法**：mock + temp data
- **校验**：`result.response == '业务代码合计约 3200 行。'; result.tool_calls == [{'name': 'run_shell', 'arguments': {'command': "find src -name '*.py' | xargs wc -l"}}]; isolated_data['router'].chat.call_count == 3`
- **位置**：`test_agent_runtime.py:153-181` · 意图由函数名推断

#### 15. `test_run_agent_turn_empty_reply_gets_fallback`

- **意图**：覆盖: run agent turn empty reply gets fallback
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`'未返回有效内容' in result.response; result.tool_calls == []; isolated_data['router'].chat.call_count == 3`
- **位置**：`test_agent_runtime.py:184-191` · 意图由函数名推断

#### 16. `test_looks_incomplete_reply_detects_truncated_synthesis`

- **意图**：覆盖: looks incomplete reply detects truncated synthesis
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_looks_incomplete_reply('根据', had_tools=True); _looks_incomplete_reply('根据工具结果，', had_tools=True); not _looks_incomplete_reply('根据', had_tools=False); not _looks_incomplete_reply('业务代码合计约 3200 行，已排除 .venv 与依赖目录。', had_tools=True)`
- **位置**：`test_agent_runtime.py:194-201` · 意图由函数名推断

#### 17. `test_truncate_for_llm_keeps_head_and_tail`

- **意图**：覆盖: truncate for llm keeps head and tail
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`len(out) < len(text); '截断' in out; out.startswith('A'); out.endswith('B')`
- **位置**：`test_agent_runtime.py:204-210` · 意图由函数名推断

#### 18. `test_run_agent_turn_retries_incomplete_synthesis`

- **意图**：覆盖: run agent turn retries incomplete synthesis
- **输入**：夹具: isolated_data
- **方法**：mock + temp data
- **校验**：`result.response == '业务代码合计约 3200 行。'; isolated_data['router'].chat.call_count == 3`
- **位置**：`test_agent_runtime.py:213-228` · 意图由函数名推断

#### 19. `test_run_agent_turn_executes_xml_tool_call`

- **意图**：覆盖: run agent turn executes xml tool call
- **输入**：夹具: isolated_data
- **方法**：mock + temp data
- **校验**：`result.response == '你去年研究了 Hindsight 和 Mem0。'; result.tool_calls == [{'name': 'search_memory', 'arguments': {'query': 'Memory System 研究 去年'}}]; isolated_data['router'].chat.call_count == 2`
- **位置**：`test_agent_runtime.py:231-251` · 意图由函数名推断

#### 20. `test_run_agent_turn_returns_final_answer_after_tool`

- **意图**：覆盖: run agent turn returns final answer after tool
- **输入**：夹具: isolated_data
- **方法**：mock + temp data
- **校验**：`result.response == '你的妻子求职中，你会帮她盯简历。'; len(result.tool_calls) == 1; isolated_data['router'].chat.call_count == 2`
- **位置**：`test_agent_runtime.py:254-268` · 意图由函数名推断

#### 21. `test_run_agent_turn_executes_json_fenced_tool_call`

- **意图**：覆盖: run agent turn executes json fenced tool call
- **输入**：夹具: isolated_data
- **方法**：mock + temp data
- **校验**：`result.response == '你几年前关注 AI 视频工具。'; result.tool_calls == [{'name': 'search_knowledge', 'arguments': {'query': '几年前'}}]; isolated_data['router'].chat.call_count == 2`
- **位置**：`test_agent_runtime.py:271-288` · 意图由函数名推断

#### 22. `test_prefetch_personal_context_for_identity_question`

- **意图**：覆盖: prefetch personal context for identity question
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`ctx; '已预加载' in ctx; '未找到相关记忆' in ctx`
- **位置**：`test_agent_runtime.py:291-297` · 意图由函数名推断

#### 23. `test_prefetch_memory_browse_question`

- **意图**：覆盖: prefetch memory browse question
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`ctx; '已预加载' in ctx; '记忆库共 3 条' in ctx`
- **位置**：`test_agent_runtime.py:300-313` · 意图由函数名推断

#### 24. `test_prefetch_family_question_uses_tag_search`

- **意图**：覆盖: prefetch family question uses tag search
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`ctx; '已预加载' in ctx; query.call_args.kwargs.get('tags') == ['家庭']`
- **位置**：`test_agent_runtime.py:316-332` · 意图由函数名推断

#### 25. `test_prefetch_skips_generic_question`

- **意图**：覆盖: prefetch skips generic question
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_prefetch_personal_context('今天天气怎么样?') == ''`
- **位置**：`test_agent_runtime.py:335-336` · 意图由函数名推断

#### 26. `test_prefetch_web_context_for_news_question`

- **意图**：覆盖: prefetch web context for news question
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`ctx; '已预加载' in ctx; '今日要闻' in ctx`
- **位置**：`test_agent_runtime.py:339-345` · 意图由函数名推断

#### 27. `test_prefetch_web_context_for_current_time_question`

- **意图**：Regression: '现在几点了' must prefetch web search, not rely on model knowledge.
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`ctx; '已预加载' in ctx; '当前时间约为 11:12' in ctx`
- **位置**：`test_agent_runtime.py:348-355` · 有 docstring

#### 28. `test_prefetch_web_context_for_几点了`

- **意图**：覆盖: prefetch web context for 几点了
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`ctx`
- **位置**：`test_agent_runtime.py:358-362` · 意图由函数名推断

#### 29. `test_prefetch_web_skips_non_time_sensitive_question`

- **意图**：覆盖: prefetch web skips non time sensitive question
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_prefetch_web_context('Python 怎么写装饰器?') == ''`
- **位置**：`test_agent_runtime.py:365-366` · 意图由函数名推断

#### 30. `test_prefetch_web_skips_session_recall_question`

- **意图**：覆盖: prefetch web skips session recall question
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`_prefetch_web_context('今天的聊天记录') == ''`
- **位置**：`test_agent_runtime.py:369-372` · 意图由函数名推断

#### 31. `test_prefetch_web_stale_results_allow_research`

- **意图**：覆盖: prefetch web stale results allow research
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`'时效核对未通过' in ctx; '再调用 web_search' in ctx; '勿再调用 web_search' not in ctx`
- **位置**：`test_agent_runtime.py:375-386` · 意图由函数名推断

#### 32. `test_tool_followup_allows_research_on_freshness_failure`

- **意图**：覆盖: tool followup allows research on freshness failure
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'再调用一次 web_search' in text; '禁止在未重试的情况下' in text`
- **位置**：`test_agent_runtime.py:389-393` · 意图由函数名推断

#### 33. `test_tool_followup_checks_basics_on_ok_search`

- **意图**：覆盖: tool followup checks basics on ok search
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'时间/地点' in text; '不要再次调用工具' in text; '完整链接' in text`
- **位置**：`test_agent_runtime.py:396-400` · 意图由函数名推断

#### 34. `test_prefetch_web_requires_source_citation`

- **意图**：覆盖: prefetch web requires source citation
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`'标题与完整链接' in ctx; '勿再调用 web_search' in ctx`
- **位置**：`test_agent_runtime.py:403-410` · 意图由函数名推断

#### 35. `test_prefetch_weather_injects_home_location`

- **意图**：覆盖: prefetch weather injects home location
- **输入**：夹具: isolated_data
- **方法**：mock + temp data
- **校验**：`ctx; '其他城市' not in ctx`
- **位置**：`test_agent_runtime.py:413-421` · 意图由函数名推断

#### 36. `test_prefetch_weather_without_home_still_searches`

- **意图**：覆盖: prefetch weather without home still searches
- **输入**：夹具: isolated_data
- **方法**：mock + temp data
- **校验**：`ctx; '其他城市' not in ctx`
- **位置**：`test_agent_runtime.py:424-429` · 意图由函数名推断

#### 37. `test_prefetch_session_context_loads_today_messages`

- **意图**：覆盖: prefetch session context loads today messages
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`'已预加载' in ctx; '介绍一下我的军事策略' in ctx; '我今天问了啥?' in ctx`
- **位置**：`test_agent_runtime.py:432-446` · 意图由函数名推断

#### 38. `test_run_agent_turn_prefetches_session_recall_without_web`

- **意图**：覆盖: run agent turn prefetches session recall without web
- **输入**：夹具: isolated_data
- **方法**：mock + temp data
- **校验**：`'军事策略' in result.response; '对话记录' in system_prompt`
- **位置**：`test_agent_runtime.py:449-464` · 意图由函数名推断

#### 39. `test_build_system_prompt_includes_prefetched_context`

- **意图**：覆盖: build system prompt includes prefetched context
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'姓名: 测试' in prompt; '摘要: 新闻' in prompt; 'search_memory' in prompt; '证据核对' in prompt; '今天是' in prompt`
- **位置**：`test_agent_runtime.py:467-476` · 意图由函数名推断

#### 40. `test_run_agent_turn_prefetches_without_tool_round`

- **意图**：覆盖: run agent turn prefetches without tool round
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + mock + temp data
- **校验**：`result.response == '你是 LocalAgent 用户。'; result.tool_calls == []; '已预加载' in system_prompt`
- **位置**：`test_agent_runtime.py:479-489` · 意图由函数名推断

#### 41. `test_run_agent_turn_prefetches_memory_browse`

- **意图**：覆盖: run agent turn prefetches memory browse
- **输入**：夹具: isolated_data
- **方法**：mock + temp data
- **校验**：`'有趣' in result.response; result.tool_calls == []; '已预加载' in system_prompt; '记忆库共 5 条' in system_prompt`
- **位置**：`test_agent_runtime.py:492-510` · 意图由函数名推断

#### 42. `test_run_agent_turn_prefetches_web_for_news`

- **意图**：覆盖: run agent turn prefetches web for news
- **输入**：夹具: isolated_data
- **方法**：mock + temp data
- **校验**：`result.response == '以下是最近新闻。'; result.tool_calls == []; '联网搜索结果' in system_prompt; '今日要闻' in system_prompt`
- **位置**：`test_agent_runtime.py:513-524` · 意图由函数名推断

#### 43. `test_run_agent_turn_prefetches_web_for_current_time`

- **意图**：Regression: asking the current time must trigger web search prefetch.
- **输入**：夹具: isolated_data
- **方法**：mock + temp data
- **校验**：`result.response == '现在大约是上午 11:12。'; result.tool_calls == []; '联网搜索结果' in system_prompt; '当前本地时间 11:12' in system_prompt`
- **位置**：`test_agent_runtime.py:527-539` · 有 docstring

#### 44. `test_needs_file_tool_retry_detects_hallucinated_write`

- **意图**：覆盖: needs file tool retry detects hallucinated write
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_needs_file_tool_retry('内容写:这是我的测试文本', '已为你更新 `test.txt` 文件，当前内容为：hello', [])`
- **位置**：`test_agent_runtime.py:542-547` · 意图由函数名推断

#### 45. `test_needs_file_tool_retry_detects_append_hallucination`

- **意图**：覆盖: needs file tool retry detects append hallucination
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_needs_file_tool_retry('追加内容:第二行内容是这样的,闲杂时间', '已成功将"第二行内容"追加到 `test.txt` 文件中。当前文件完整内容为：\n\n', [])`
- **位置**：`test_agent_runtime.py:550-555` · 意图由函数名推断

#### 46. `test_needs_file_tool_retry_detects_direct_write_without_claim`

- **意图**：覆盖: needs file tool retry detects direct write without claim
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_needs_file_tool_retry('追加内容:第二行', '好的。', [])`
- **位置**：`test_agent_runtime.py:558-563` · 意图由函数名推断

#### 47. `test_needs_file_tool_retry_ignores_clarification`

- **意图**：覆盖: needs file tool retry ignores clarification
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`not _needs_file_tool_retry('修改根目录下的test.txt文件', '请告诉我具体的修改内容或目标要求。', [])`
- **位置**：`test_agent_runtime.py:566-571` · 意图由函数名推断

#### 48. `test_needs_file_tool_retry_ignores_when_tool_called`

- **意图**：覆盖: needs file tool retry ignores when tool called
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`not _needs_file_tool_retry('内容写:这是我的测试文本', '已为你更新 test.txt', [{'name': 'write_file', 'arguments': {'path': 'test.txt', 'content': 'hello'}}]`
- **位置**：`test_agent_runtime.py:574-579` · 意图由函数名推断

#### 49. `test_run_agent_turn_retries_when_file_write_claimed_without_tool`

- **意图**：覆盖: run agent turn retries when file write claimed without tool
- **输入**：夹具: isolated_data
- **方法**：mock + temp data
- **校验**：`result.response == '文件已更新。'; result.tool_calls == [{'name': 'write_file', 'arguments': {'path': 'test.txt', 'content': '新内容'}}]; isolated_data['router'].chat.call_count == 3`
- **位置**：`test_agent_runtime.py:582-601` · 意图由函数名推断

#### 50. `test_run_agent_turn_retries_append_hallucination`

- **意图**：覆盖: run agent turn retries append hallucination
- **输入**：夹具: isolated_data
- **方法**：mock + temp data
- **校验**：`result.response == '已追加第二行。'; result.tool_calls[0]['arguments']['mode'] == 'append'`
- **位置**：`test_agent_runtime.py:604-627` · 意图由函数名推断

#### 51. `test_run_agent_turn_fails_gracefully_after_retry_exhausted`

- **意图**：覆盖: run agent turn fails gracefully after retry exhausted
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`'未能实际写入文件' in result.response; result.tool_calls == []`
- **位置**：`test_agent_runtime.py:630-639` · 意图由函数名推断

#### 52. `test_parse_write_file_tool_call`

- **意图**：覆盖: parse write file tool call
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_parse_tool_call(text) == {'name': 'write_file', 'arguments': {'path': 'test.txt', 'content': 'hello'}}`
- **位置**：`test_agent_runtime.py:642-650` · 意图由函数名推断

#### 53. `test_run_agent_turn_none_reply_treated_as_empty`

- **意图**：覆盖: run agent turn none reply treated as empty
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`result.response == '你好，我是 LocalAgent'; isolated_data['router'].chat.call_count == 2`
- **位置**：`test_agent_runtime.py:653-659` · 意图由函数名推断


### `test_approval.py`（14）

#### 1. `test_normalize_approval_policy`

- **意图**：覆盖: normalize approval policy
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`normalize_approval_policy('always') == 'always'; normalize_approval_policy('dangerous') == 'dangerous'; normalize_approval_policy('off') == 'off'; normalize_approval_policy('never') == 'off'; normalize_approval_policy('weird') == 'always'`
- **位置**：`test_approval.py:18-23` · 意图由函数名推断

#### 2. `test_classify_shell_blocks_rm_rf_root`

- **意图**：覆盖: classify shell blocks rm rf root
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`risk.level == 'blocked'; risk.reason`
- **位置**：`test_approval.py:26-29` · 意图由函数名推断

#### 3. `test_classify_shell_marks_rm_dangerous`

- **意图**：覆盖: classify shell marks rm dangerous
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`risk.level == 'dangerous'; '删除' in (risk.reason or '')`
- **位置**：`test_approval.py:32-35` · 意图由函数名推断

#### 4. `test_classify_shell_marks_sudo_dangerous`

- **意图**：覆盖: classify shell marks sudo dangerous
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`classify_shell_command('sudo apt install foo').level == 'dangerous'`
- **位置**：`test_approval.py:38-39` · 意图由函数名推断

#### 5. `test_classify_shell_safe_read`

- **意图**：覆盖: classify shell safe read
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`classify_shell_command('ls -la').level == 'safe'; classify_shell_command("find . -name '*.py' | wc -l").level == 'safe'`
- **位置**：`test_approval.py:42-44` · 意图由函数名推断

#### 6. `test_classify_write_file_is_dangerous`

- **意图**：覆盖: classify write file is dangerous
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`risk.level == 'dangerous'; 'a.txt' in risk.summary`
- **位置**：`test_approval.py:47-50` · 意图由函数名推断

#### 7. `test_needs_approval_policy_always`

- **意图**：覆盖: needs approval policy always
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`needs_approval('run_shell', risk, policy='always'); not needs_approval('run_shell', risk, policy='dangerous'); not needs_approval('run_shell', risk, policy='off')`
- **位置**：`test_approval.py:53-57` · 意图由函数名推断

#### 8. `test_needs_approval_policy_dangerous`

- **意图**：覆盖: needs approval policy dangerous
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`needs_approval('run_shell', risk, policy='dangerous'); needs_approval('write_file', write_risk, policy='dangerous')`
- **位置**：`test_approval.py:60-64` · 意图由函数名推断

#### 9. `test_needs_approval_skips_blocked`

- **意图**：覆盖: needs approval skips blocked
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`risk.level == 'blocked'; not needs_approval('run_shell', risk, policy='always')`
- **位置**：`test_approval.py:67-70` · 意图由函数名推断

#### 10. `test_format_approval_prompt_includes_command`

- **意图**：覆盖: format approval prompt includes command
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'rm -rf ./tmp' in text; '风险' in text`
- **位置**：`test_approval.py:73-77` · 意图由函数名推断

#### 11. `test_prompt_tool_approval_non_tty_denies`

- **意图**：覆盖: prompt tool approval non tty denies
- **输入**：无外部夹具
- **方法**：mock
- **校验**：`prompt_tool_approval('run_shell', {'command': 'ls'}, risk) is False`
- **位置**：`test_approval.py:80-84` · 意图由函数名推断

#### 12. `test_run_agent_turn_requests_approval_and_denies`

- **意图**：覆盖: run agent turn requests approval and denies
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + mock + temp data
- **校验**：`approvals == ['run_shell']; '跳过' in result.response or result.tool_calls`
- **位置**：`test_approval.py:87-112` · 意图由函数名推断

#### 13. `test_run_agent_turn_approves_and_executes`

- **意图**：覆盖: run agent turn approves and executes
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + mock + temp data
- **校验**：`result.response == '命令输出为 hello。'`
- **位置**：`test_approval.py:115-134` · 意图由函数名推断

#### 14. `test_run_agent_turn_blocks_without_callback`

- **意图**：覆盖: run agent turn blocks without callback
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + mock + temp data
- **校验**：`result.tool_calls`
- **位置**：`test_approval.py:137-152` · 意图由函数名推断


### `test_files.py`（4）

#### 1. `test_write_file_tool_overwrite`

- **意图**：覆盖: write file tool overwrite
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`'已写入文件' in result; target.read_text(encoding='utf-8') == 'hello world'`
- **位置**：`test_files.py:11-16` · 意图由函数名推断

#### 2. `test_write_file_tool_append`

- **意图**：覆盖: write file tool append
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`'已追加文件' in result; target.read_text(encoding='utf-8') == 'line1\nline2\n'`
- **位置**：`test_files.py:19-26` · 意图由函数名推断

#### 3. `test_write_file_tool_blocks_path_outside_workspace`

- **意图**：覆盖: write file tool blocks path outside workspace
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`'必须位于工作区内' in result; not outside.exists()`
- **位置**：`test_files.py:29-34` · 意图由函数名推断

#### 4. `test_execute_tool_write_file`

- **意图**：覆盖: execute tool write file
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`'已写入文件' in result; (tmp_path / 'nested' / 'out.txt').read_text(encoding='utf-8') == 'nested content'`
- **位置**：`test_files.py:37-44` · 意图由函数名推断


### `test_shell.py`（6）

#### 1. `test_run_shell_command_echo`

- **意图**：覆盖: run shell command echo
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`'hello' in result; 'stdout:' in result; str(tmp_path) in result`
- **位置**：`test_shell.py:11-15` · 意图由函数名推断

#### 2. `test_run_shell_command_empty`

- **意图**：覆盖: run shell command empty
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'不能为空' in run_shell_command('   ')`
- **位置**：`test_shell.py:18-19` · 意图由函数名推断

#### 3. `test_run_shell_command_blocks_rm_rf_root`

- **意图**：覆盖: run shell command blocks rm rf root
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'禁止' in result`
- **位置**：`test_shell.py:22-24` · 意图由函数名推断

#### 4. `test_run_shell_command_timeout`

- **意图**：覆盖: run shell command timeout
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`'超时' in result`
- **位置**：`test_shell.py:27-29` · 意图由函数名推断

#### 5. `test_execute_tool_run_shell`

- **意图**：覆盖: execute tool run shell
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`str(tmp_path) in result`
- **位置**：`test_shell.py:32-34` · 意图由函数名推断

#### 6. `test_parse_run_shell_tool_call`

- **意图**：覆盖: parse run shell tool call
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`_parse_tool_call(text) == {'name': 'run_shell', 'arguments': {'command': 'wc -l *.py'}}`
- **位置**：`test_shell.py:37-44` · 意图由函数名推断


### `test_web_search.py`（34）

#### 1. `test_augment_web_query_adds_current_month`

- **意图**：覆盖: augment web query adds current month
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`f'{today.year}年{today.month:02d}月' in augment_web_query('最近科技新闻')`
- **位置**：`test_web_search.py:20-22` · 意图由函数名推断

#### 2. `test_augment_web_query_today_uses_full_date`

- **意图**：覆盖: augment web query today uses full date
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'2026年7月14日' in out`
- **位置**：`test_web_search.py:25-28` · 意图由函数名推断

#### 3. `test_inject_home_location_for_weather`

- **意图**：覆盖: inject home location for weather
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`inject_home_location_for_weather('今天天气怎么样?') == '深圳 今天天气怎么样?'; inject_home_location_for_weather('深圳今天天气') == '深圳今天天气'; inject_home_location_for_weather('最近有什么新闻') == '最近有什么新闻'; prepared.startswith('深圳'); '今天' in prepared`
- **位置**：`test_web_search.py:31-43` · 意图由函数名推断

#### 4. `test_weather_query_strips_year_date`

- **意图**：Full calendar dates in weather searches pull archives and fail freshness.
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'2026年' not in out; '深圳' in out; '今天' in out; '2026年' not in tomorrow; '明天' in tomorrow`
- **位置**：`test_web_search.py:46-60` · 有 docstring

#### 5. `test_inject_home_skips_without_profile`

- **意图**：覆盖: inject home skips without profile
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`inject_home_location_for_weather('今天天气怎么样?') == '今天天气怎么样?'`
- **位置**：`test_web_search.py:62-65` · 意图由函数名推断

#### 6. `test_extract_searchable_query_unwraps_assume_block`

- **意图**：覆盖: extract searchable query unwraps assume block
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`extract_searchable_query(wrapped) == '今天天气怎么样?'`
- **位置**：`test_web_search.py:68-76` · 意图由函数名推断

#### 7. `test_augment_web_query_tomorrow_uses_next_day`

- **意图**：覆盖: augment web query tomorrow uses next day
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'2026年7月15日' in out; '2026年7月14日' not in out`
- **位置**：`test_web_search.py:79-83` · 意图由函数名推断

#### 8. `test_query_target_date_tomorrow`

- **意图**：覆盖: query target date tomorrow
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`query_target_date('明天北京天气', today=date(2026, 7, 14)) == date(2026, 7, 15); query_target_date('北京今天天气', today=date(2026, 7, 14)) == date(2026, 7, 14)`
- **位置**：`test_web_search.py:86-90` · 意图由函数名推断

#### 9. `test_augment_web_query_keeps_explicit_year`

- **意图**：覆盖: augment web query keeps explicit year
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`augment_web_query('2024年科技新闻') == '2024年科技新闻'`
- **位置**：`test_web_search.py:93-94` · 意图由函数名推断

#### 10. `test_derive_search_params_news_recent`

- **意图**：覆盖: derive search params news recent
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`opts['topic'] == 'news'; opts['days'] == 7`
- **位置**：`test_web_search.py:97-100` · 意图由函数名推断

#### 11. `test_derive_search_params_news_today`

- **意图**：覆盖: derive search params news today
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`opts['topic'] == 'news'; opts['days'] == 1`
- **位置**：`test_web_search.py:103-106` · 意图由函数名推断

#### 12. `test_derive_search_params_recent_non_news`

- **意图**：覆盖: derive search params recent non news
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`opts['time_range'] == 'week'; 'topic' not in opts`
- **位置**：`test_web_search.py:109-112` · 意图由函数名推断

#### 13. `test_derive_search_params_current_time`

- **意图**：覆盖: derive search params current time
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`opts['time_range'] == 'day'; 'topic' not in opts`
- **位置**：`test_web_search.py:115-118` · 意图由函数名推断

#### 14. `test_derive_search_params_weather_uses_day`

- **意图**：覆盖: derive search params weather uses day
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`opts['time_range'] == 'day'`
- **位置**：`test_web_search.py:121-123` · 意图由函数名推断

#### 15. `test_query_recency_mode_weather`

- **意图**：覆盖: query recency mode weather
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`query_recency_mode('深圳今天天气预报') == 'day'`
- **位置**：`test_web_search.py:126-127` · 意图由函数名推断

#### 16. `test_resolve_provider_auto_prefers_tavily`

- **意图**：覆盖: resolve provider auto prefers tavily
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`resolve_web_search_provider() == 'tavily'`
- **位置**：`test_web_search.py:130-134` · 意图由函数名推断

#### 17. `test_resolve_provider_auto_prefers_searxng_without_tavily`

- **意图**：覆盖: resolve provider auto prefers searxng without tavily
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`resolve_web_search_provider() == 'searxng'`
- **位置**：`test_web_search.py:137-141` · 意图由函数名推断

#### 18. `test_resolve_provider_auto_falls_back_to_ddgs`

- **意图**：覆盖: resolve provider auto falls back to ddgs
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`resolve_web_search_provider() == 'ddgs'`
- **位置**：`test_web_search.py:144-148` · 意图由函数名推断

#### 19. `test_resolve_provider_explicit_ddgs`

- **意图**：覆盖: resolve provider explicit ddgs
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`resolve_web_search_provider() == 'ddgs'`
- **位置**：`test_web_search.py:151-154` · 意图由函数名推断

#### 20. `test_extract_dates_from_chinese_and_iso`

- **意图**：覆盖: extract dates from chinese and iso
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`date(2026, 3, 1) in dates; date(2026, 7, 14) in dates`
- **位置**：`test_web_search.py:157-160` · 意图由函数名推断

#### 21. `test_classify_stale_march_weather_in_july`

- **意图**：覆盖: classify stale march weather in july
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`label == 'stale'; hit == date(2026, 3, 15)`
- **位置**：`test_web_search.py:163-176` · 意图由函数名推断

#### 22. `test_classify_fresh_july_weather`

- **意图**：覆盖: classify fresh july weather
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`label == 'fresh'; hit == date(2026, 7, 14)`
- **位置**：`test_web_search.py:179-192` · 意图由函数名推断

#### 23. `test_format_search_output_rejects_stale_as_current`

- **意图**：覆盖: format search output rejects stale as current
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'【检索基准日】' in text; today_label(today) in text; '【核对失败】' in text; search_output_has_freshness_warning(text); '今日大雨' not in text`
- **位置**：`test_web_search.py:195-216` · 意图由函数名推断

#### 24. `test_format_search_output_keeps_fresh_and_filters_stale`

- **意图**：覆盖: format search output keeps fresh and filters stale
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'摘要: 今日多云' in text; '新页' in text; '【时效警告】' in text; '已过滤的过期结果' in text; '过期页' in text`
- **位置**：`test_web_search.py:219-244` · 意图由函数名推断

#### 25. `test_format_search_output`

- **意图**：覆盖: format search output
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'摘要: 摘要句' in text; '标题' in text; '2026-07-11' in text; 'https://example.com' in text; '来源: 标题' in text`
- **位置**：`test_web_search.py:247-268` · 意图由函数名推断

#### 26. `test_format_search_output_tomorrow_uses_target_date`

- **意图**：覆盖: format search output tomorrow uses target date
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'【检索基准日】2026年7月15日' in text; '【日历今天】2026年7月14日' in text; '明天/次日' in text; '链接: https://example.com/bj-tomorrow' in text; '【引用要求】' in text`
- **位置**：`test_web_search.py:271-289` · 意图由函数名推断

#### 27. `test_web_search_sends_recency_payload`

- **意图**：覆盖: web search sends recency payload
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch + mock
- **校验**：`payload['topic'] == 'news'; payload['days'] == 7; payload['include_answer'] is True; f'{today.year}年{today.month:02d}月' in payload['query']; '今日要闻摘要' in result`
- **位置**：`test_web_search.py:292-325` · 意图由函数名推断

#### 28. `test_web_search_ddgs_text`

- **意图**：覆盖: web search ddgs text
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch + mock
- **校验**：`'AI 进展' in result; 'https://example.com/ai' in result; '模型发布' in result; kwargs['max_results'] == 5; kwargs.get('timelimit') == 'w'`
- **位置**：`test_web_search.py:328-346` · 意图由函数名推断

#### 29. `test_web_search_ddgs_news`

- **意图**：覆盖: web search ddgs news
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch + mock
- **校验**：`'今日头条' in result; '2026-07-13' in result; mock_ddgs.news.call_args.kwargs.get('timelimit') == 'w'`
- **位置**：`test_web_search.py:349-368` · 意图由函数名推断

#### 30. `test_web_search_searxng`

- **意图**：覆盖: web search searxng
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch + mock
- **校验**：`'SearX 结果' in result; 'https://example.com/sx' in result; call_kwargs.args[0] == 'http://searx.local:8080/search'; params['format'] == 'json'; params['categories'] == 'news'`
- **位置**：`test_web_search.py:371-404` · 意图由函数名推断

#### 31. `test_web_search_tavily_missing_key`

- **意图**：覆盖: web search tavily missing key
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`result.startswith('联网搜索未配置'); 'TAVILY_API_KEY' in result`
- **位置**：`test_web_search.py:407-412` · 意图由函数名推断

#### 32. `test_weather_search_unusable_detects_junk_and_failure`

- **意图**：覆盖: weather search unusable detects junk and failure
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`weather_search_unusable('【核对失败】没有匹配'); weather_search_unusable('【时效警告】\n- [日期未知] 歌词_今天天气怎么样.pdf: 儿歌'); not weather_search_unusable('【时效核对】匹配 1 条\n- [匹配·2026-07-14] 深圳今日天气: 多云 28°C')`
- **位置**：`test_web_search.py:415-424` · 意图由函数名推断

#### 33. `test_weather_retry_queries_include_forecast`

- **意图**：覆盖: weather retry queries include forecast
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`any(('深圳' in q and '天气预报' in q for q in alts))`
- **位置**：`test_web_search.py:427-433` · 意图由函数名推断

#### 34. `test_web_search_retries_unusable_weather`

- **意图**：覆盖: web search retries unusable weather
- **输入**：夹具: monkeypatch, isolated_data
- **方法**：monkeypatch + mock + temp data
- **校验**：`'深圳今天天气预报' in result or '多云' in result; len(calls) >= 2; '核对失败' not in result`
- **位置**：`test_web_search.py:436-466` · 意图由函数名推断


## Ingest/Tasks

### `test_ingest.py`（7）

#### 1. `test_add_file_symlinks_and_indexes_cold_only`

- **意图**：rag add: symlink + Cold RAG; short docs skip Warm summary by default.
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`target == config.KB_DIR / 'diary.md'; target.is_symlink(); os.readlink(target) == str(source.resolve()); result.status == IngestStatus.NEW; result.memory_fact_count == 0`
- **位置**：`test_ingest.py:22-39` · 有 docstring

#### 2. `test_sync_file_skips_unchanged`

- **意图**：覆盖: sync file skips unchanged
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`summary1.skipped_count == 1; summary2.skipped_count == 1`
- **位置**：`test_ingest.py:42-50` · 意图由函数名推断

#### 3. `test_sync_file_updates_changed_file`

- **意图**：覆盖: sync file updates changed file
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`summary.updated_count == 1`
- **位置**：`test_ingest.py:53-58` · 意图由函数名推断

#### 4. `test_reset_knowledge_and_rebuild`

- **意图**：覆盖: reset knowledge and rebuild
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`get_knowledge_indexer().count() > 0; chat_before >= 1; stats['knowledge_chunks_removed'] >= 0; get_knowledge_indexer().count() == 0; get_memory_store().count() == chat_before`
- **位置**：`test_ingest.py:61-77` · 意图由函数名推断

#### 5. `test_save_facts_flow`

- **意图**：覆盖: save facts flow
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`len(ids) == 1; get_memory_store().count() == before + 1`
- **位置**：`test_ingest.py:80-87` · 意图由函数名推断

#### 6. `test_core_profile_roundtrip`

- **意图**：覆盖: core profile roundtrip
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`loaded.name == '测试用户'`
- **位置**：`test_ingest.py:90-94` · 意图由函数名推断

#### 7. `test_memory_reset_preserves_knowledge`

- **意图**：覆盖: memory reset preserves knowledge
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`chunks > 0; get_memory_store().count() == 0; get_knowledge_indexer().count() == chunks`
- **位置**：`test_ingest.py:97-106` · 意图由函数名推断


### `test_tasks.py`（7）

#### 1. `test_add_file_background_creates_task`

- **意图**：覆盖: add file background creates task
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`target.is_symlink(); task.id.startswith('t-'); pid > 0; task.log_path; Path(task.log_path).exists()`
- **位置**：`test_tasks.py:18-34` · 意图由函数名推断

#### 2. `test_worker_completes_task`

- **意图**：覆盖: worker completes task
- **输入**：夹具: tmp_path, isolated_data
- **方法**：mock + temp data
- **校验**：`rc == 0; loaded is not None; loaded.status == TaskStatus.COMPLETED; loaded.memory_fact_count == 2; '完成' in read_task_log(task.id)`
- **位置**：`test_tasks.py:37-58` · 意图由函数名推断

#### 3. `test_task_delete`

- **意图**：覆盖: task delete
- **输入**：夹具: tmp_path
- **方法**：mock + temp data
- **校验**：`deleted is not None; get_task_store().get(task.id) is None; not Path(task.log_path).exists()`
- **位置**：`test_tasks.py:61-70` · 意图由函数名推断

#### 4. `test_task_pause_and_resume`

- **意图**：覆盖: task pause and resume
- **输入**：夹具: tmp_path
- **方法**：mock + temp data
- **校验**：`paused is not None; paused.status == TaskStatus.PAUSED; resumed is not None; resumed.status == TaskStatus.RUNNING`
- **位置**：`test_tasks.py:73-87` · 意图由函数名推断

#### 5. `test_task_restart`

- **意图**：覆盖: task restart
- **输入**：夹具: tmp_path
- **方法**：mock + temp data
- **校验**：`pid == 99999; restarted.status == TaskStatus.QUEUED; '任务重启中' in read_task_log(task.id)`
- **位置**：`test_tasks.py:90-111` · 意图由函数名推断

#### 6. `test_task_reconcile_stale`

- **意图**：覆盖: task reconcile stale
- **输入**：夹具: tmp_path
- **方法**：mock + temp data
- **校验**：`changed >= 1; loaded is not None; loaded.status == TaskStatus.FAILED`
- **位置**：`test_tasks.py:114-134` · 意图由函数名推断

#### 7. `test_foreground_add_file_shows_progress`

- **意图**：覆盖: foreground add file shows progress
- **输入**：夹具: tmp_path, capsys
- **方法**：stdout + temp data
- **校验**：`'源文件' in out; '加载文件' in out; '知识库' in out or 'chunks' in out`
- **位置**：`test_tasks.py:137-149` · 意图由函数名推断


## CLI/UX

### `test_chat.py`（11）

#### 1. `test_chat_shows_response_provider`

- **意图**：覆盖: chat shows response provider
- **输入**：夹具: capsys, monkeypatch
- **方法**：monkeypatch + mock + stdout
- **校验**：`'[via openrouter/anthropic/claude-sonnet-4]' in output`
- **位置**：`test_chat.py:14-31` · 意图由函数名推断

#### 2. `test_chat_shows_error_for_empty_response`

- **意图**：覆盖: chat shows error for empty response
- **输入**：夹具: capsys, monkeypatch
- **方法**：monkeypatch + mock + stdout
- **校验**：`'模型返回了空内容' in output; '[via ollama/qwen3.5:4b]' in output`
- **位置**：`test_chat.py:34-52` · 意图由函数名推断

#### 3. `test_chat_persists_conversation_to_jsonl`

- **意图**：PRD §4: chat 对话持久化到 data/conversations/*.jsonl.
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch + mock
- **校验**：`len(messages) == 2; messages[0]['role'] == 'user'; messages[0]['content'] == '你好'; messages[1]['role'] == 'assistant'; 'LocalAgent' in messages[1]['content']`
- **位置**：`test_chat.py:55-74` · 有 docstring

#### 4. `test_chat_exit_schedules_background_extract`

- **意图**：对话退出时在后台提取记忆，不阻塞 REPL.
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + mock + temp data
- **校验**：`after >= before + 1; any(('Hindsight' in t for t in texts))`
- **位置**：`test_chat.py:77-103` · 有 docstring

#### 5. `test_chat_exit_extract_runs_in_background`

- **意图**：退出时不等待记忆提取完成.
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`scheduled == ['s-bg']`
- **位置**：`test_chat.py:106-122` · 有 docstring

#### 6. `test_chat_skips_extraction_for_empty_session`

- **意图**：覆盖: chat skips extraction for empty session
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`get_memory_store().count() == before`
- **位置**：`test_chat.py:125-131` · 意图由函数名推断

#### 7. `test_chat_deepsearch_persisted`

- **意图**：覆盖: chat deepsearch persisted
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch + mock
- **校验**：`len(messages) == 2; 'deepsearch' in messages[0]['content']; messages[1].get('tool') == 'deepsearch'; '深度研究报告' in messages[1]['content']`
- **位置**：`test_chat.py:134-149` · 意图由函数名推断

#### 8. `test_chat_slash_help_and_quit`

- **意图**：覆盖: chat slash help and quit
- **输入**：夹具: monkeypatch, capsys
- **方法**：monkeypatch + mock + stdout
- **校验**：`'/provider' in out; '/model' in out; 'add' in out`
- **位置**：`test_chat.py:152-167` · 意图由函数名推断

#### 9. `test_chat_provider_switch_passes_to_agent`

- **意图**：覆盖: chat provider switch passes to agent
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch + mock
- **校验**：`mock_turn.call_args.kwargs['provider'] == 'ollama'`
- **位置**：`test_chat.py:170-183` · 意图由函数名推断

#### 10. `test_chat_single_ctrl_c_does_not_exit`

- **意图**：First Ctrl+C at prompt cancels input; REPL stays alive.
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch + mock
- **校验**：`rc == 0; len(messages) == 2; messages[0]['content'] == 'hello'`
- **位置**：`test_chat.py:186-210` · 有 docstring

#### 11. `test_chat_ctrl_c_during_inference_keeps_repl`

- **意图**：覆盖: chat ctrl c during inference keeps repl
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch + mock
- **校验**：`messages == []`
- **位置**：`test_chat.py:213-226` · 意图由函数名推断


### `test_cli.py`（20）

#### 1. `test_cli_bare_memory_shows_status`

- **意图**：Bare `LA memory` defaults to status overview (no argparse error).
- **输入**：夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; '[memory status]' in out; '来源分布' in out; '下一步' in out; 'memory query' in out`
- **位置**：`test_cli.py:21-29` · 有 docstring

#### 2. `test_cli_bare_rag_shows_status`

- **意图**：Bare `LA rag` defaults to status overview (no argparse error).
- **输入**：夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; '[rag status]' in out; 'kb 目录' in out; '下一步' in out; 'rag search' in out`
- **位置**：`test_cli.py:32-40` · 有 docstring

#### 3. `test_cli_version_flag`

- **意图**：覆盖: cli version flag
- **输入**：夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`main(['--version']) == 0; f'la-localagent {__version__}' in capsys.readouterr().out`
- **位置**：`test_cli.py:43-45` · 意图由函数名推断

#### 4. `test_cli_version_short_flag`

- **意图**：覆盖: cli version short flag
- **输入**：夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`main(['-V']) == 0; f'la-localagent {__version__}' in capsys.readouterr().out`
- **位置**：`test_cli.py:48-50` · 意图由函数名推断

#### 5. `test_build_parser_exposes_version`

- **意图**：覆盖: build parser exposes version
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'--version' in help_text; '-V' in help_text; 'rag' in help_text`
- **位置**：`test_cli.py:53-57` · 意图由函数名推断

#### 6. `test_cli_add_writes_memory_directly`

- **意图**：PRD §3: LA memory add 直接加记忆，即时生效.
- **输入**：无外部夹具
- **方法**：CLI/subprocess
- **校验**：`rc == 0; get_memory_store().count() == before + 1`
- **位置**：`test_cli.py:60-65` · 有 docstring

#### 7. `test_cli_add_rejects_low_value_text`

- **意图**：覆盖: cli add rejects low value text
- **输入**：夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 1; '未写入' in capsys.readouterr().out`
- **位置**：`test_cli.py:68-71` · 意图由函数名推断

#### 8. `test_cli_rag_add_and_ingest`

- **意图**：覆盖: cli rag add and ingest
- **输入**：夹具: tmp_path, capsys
- **方法**：CLI/subprocess + stdout + temp data
- **校验**：`rc == 0; '软链:' in out; (config.KB_DIR / 'journal.md').is_symlink(); get_memory_store().count() == before; rc == 0`
- **位置**：`test_cli.py:74-90` · 意图由函数名推断

#### 9. `test_cli_memory_add_file_moved`

- **意图**：覆盖: cli memory add file moved
- **输入**：夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 2; 'rag add' in capsys.readouterr().out`
- **位置**：`test_cli.py:93-96` · 意图由函数名推断

#### 10. `test_cli_search_memory_after_add`

- **意图**：覆盖: cli search memory after add
- **输入**：无外部夹具
- **方法**：CLI/subprocess
- **校验**：`hits; 'Hindsight' in hits`
- **位置**：`test_cli.py:99-103` · 意图由函数名推断

#### 11. `test_cli_search_knowledge_after_rag_add`

- **意图**：覆盖: cli search knowledge after rag add
- **输入**：夹具: tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`hits; 'Hindsight' in hits`
- **位置**：`test_cli.py:106-115` · 意图由函数名推断

#### 12. `test_cli_forget_memory`

- **意图**：覆盖: cli forget memory
- **输入**：无外部夹具
- **方法**：CLI/subprocess
- **校验**：`hits; rc == 0; get_memory_store().get(fact_id) is None`
- **位置**：`test_cli.py:118-126` · 意图由函数名推断

#### 13. `test_cli_search_shows_memory_ids`

- **意图**：覆盖: cli search shows memory ids
- **输入**：无外部夹具
- **方法**：CLI/subprocess
- **校验**：`hits; rc == 0`
- **位置**：`test_cli.py:129-135` · 意图由函数名推断

#### 14. `test_cli_rememorize_chat`

- **意图**：From conversation archive (jsonl migrates) extract memories.
- **输入**：夹具: isolated_data
- **方法**：CLI/subprocess + temp data
- **校验**：`rc == 0; get_memory_store().count() == before + 1`
- **位置**：`test_cli.py:138-158` · 有 docstring

#### 15. `test_cli_reset_memory_preserves_rag`

- **意图**：覆盖: cli reset memory preserves rag
- **输入**：夹具: tmp_path, capsys
- **方法**：CLI/subprocess + stdout + temp data
- **校验**：`get_memory_store().count() > 0; get_sync_index().get('doc.md') is not None; rc == 0; 'memory reset' in out; get_memory_store().count() == 0`
- **位置**：`test_cli.py:161-176` · 意图由函数名推断

#### 16. `test_cli_rag_rebuild`

- **意图**：覆盖: cli rag rebuild
- **输入**：夹具: tmp_path, capsys
- **方法**：CLI/subprocess + stdout + temp data
- **校验**：`rc == 0; 'rag rebuild' in out; get_sync_index().get('rebuild.md') is not None`
- **位置**：`test_cli.py:179-188` · 意图由函数名推断

#### 17. `test_cli_deprecated_flat_commands`

- **意图**：覆盖: cli deprecated flat commands
- **输入**：夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 2; '已废弃' in out; 'memory add' in out; rc == 2; 'rag ingest' in out`
- **位置**：`test_cli.py:191-201` · 意图由函数名推断

#### 18. `test_cli_ingest_chat_skips_when_unchanged`

- **意图**：覆盖: cli ingest chat skips when unchanged
- **输入**：夹具: isolated_data, capsys
- **方法**：CLI/subprocess + stdout + temp data
- **校验**：`main(['memory', 'ingest', 'chat', '--session', session_id]) == 0; main(['memory', 'ingest', 'chat', '--session', session_id]) == 0; get_memory_store().count() == count; '跳过' in out or '未提取到新记忆' in out`
- **位置**：`test_cli.py:204-225` · 意图由函数名推断

#### 19. `test_cli_rag_add_missing_path`

- **意图**：覆盖: cli rag add missing path
- **输入**：夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 1; 'error' in capsys.readouterr().out.lower()`
- **位置**：`test_cli.py:228-231` · 意图由函数名推断

#### 20. `test_search_documents_reads_kb_files`

- **意图**：覆盖: search documents reads kb files
- **输入**：夹具: tmp_path
- **方法**：mock + CLI/subprocess + temp data
- **校验**：`'Hindsight' in result; 'notes.md' in result or '记忆和 RAG 均未命中' in result`
- **位置**：`test_cli.py:234-251` · 意图由函数名推断


### `test_completion.py`（27）

#### 1. `test_complete_subcommand_prefix_memory`

- **意图**：覆盖: complete subcommand prefix memory
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'memory' in hits; 'approve' not in hits`
- **位置**：`test_completion.py:14-17` · 意图由函数名推断

#### 2. `test_complete_all_subcommands_from_empty`

- **意图**：覆盖: complete all subcommands from empty
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'chat' in hits; 'memory' in hits; 'rag' in hits; 'tasks' in hits; 'add-file' not in hits`
- **位置**：`test_completion.py:20-27` · 意图由函数名推断

#### 3. `test_complete_memory_actions`

- **意图**：覆盖: complete memory actions
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'add' in hits; 'ingest' in hits; 'query' in hits; 'search' in hits`
- **位置**：`test_completion.py:30-35` · 意图由函数名推断

#### 4. `test_complete_rag_actions`

- **意图**：覆盖: complete rag actions
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'add' in hits; 'ingest' in hits; 'search' in hits; 'rebuild' in hits`
- **位置**：`test_completion.py:38-43` · 意图由函数名推断

#### 5. `test_complete_memory_ingest_sources`

- **意图**：覆盖: complete memory ingest sources
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`set(hits) == {'chat', 'chatgpt', 'all'}`
- **位置**：`test_completion.py:46-48` · 意图由函数名推断

#### 6. `test_list_slash_command_names_excludes_chat`

- **意图**：覆盖: list slash command names excludes chat
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'chat' not in names; 'help' in names; 'h' in names; 'provider' in names; 'model' in names`
- **位置**：`test_completion.py:51-68` · 意图由函数名推断

#### 7. `test_session_slash_tab_lists_all_on_slash`

- **意图**：覆盖: session slash tab lists all on slash
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'/help' in hits; '/memory' in hits; '/rag' in hits; '/provider' in hits; '/model' in hits`
- **位置**：`test_completion.py:71-86` · 意图由函数名推断

#### 8. `test_session_slash_tab_memory_rag_subcommands`

- **意图**：覆盖: session slash tab memory rag subcommands
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'add' in mem; 'forget' in mem; 'search' in mem; 'reflect' in mem; 'add' in rag`
- **位置**：`test_completion.py:89-96` · 意图由函数名推断

#### 9. `test_session_slash_tab_prefix_filter`

- **意图**：覆盖: session slash tab prefix filter
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`hits == ['/help']`
- **位置**：`test_completion.py:99-101` · 意图由函数名推断

#### 10. `test_session_slash_tab_colon_prefix`

- **意图**：覆盖: session slash tab colon prefix
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`':help' in hits; ':provider' in hits; all((h.startswith(':') for h in hits))`
- **位置**：`test_completion.py:104-108` · 意图由函数名推断

#### 11. `test_session_slash_tab_ignores_plain_chat`

- **意图**：覆盖: session slash tab ignores plain chat
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`suggest_session_slash_completions('你好', text='你好') == []`
- **位置**：`test_completion.py:111-112` · 意图由函数名推断

#### 12. `test_session_slash_tab_provider_values_after_space`

- **意图**：覆盖: session slash tab provider values after space
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'auto' in hits; 'ollama' in hits; all((not h.startswith('/') for h in hits)); suggest_session_slash_completions('/provider oll', text='oll') == ['ollama']; 'auto' in suggest_session_slash_completions('/p ', text='')`
- **位置**：`test_completion.py:115-122` · 意图由函数名推断

#### 13. `test_session_slash_tab_provider_expands_on_exact_command`

- **意图**：覆盖: session slash tab provider expands on exact command
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`any((h.startswith('/provider ') for h in hits)); any((h.endswith(' ollama') for h in hits)); any((h.endswith(' auto') for h in hits))`
- **位置**：`test_completion.py:125-129` · 意图由函数名推断

#### 14. `test_session_slash_tab_model_values`

- **意图**：覆盖: session slash tab model values
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`suggest_session_slash_completions('/model ', text='') == []; suggest_session_slash_completions('/model lla', text='lla') == ['llama3.2:3b']; suggest_session_slash_completions('/model claude', text='claude') == ['anthropic/claude-sonnet-4']; suggest_session_slash_completions('/model', text='/model') == ['/model']; '/m' not in suggest_session_slash_completions('/m', text='/m')`
- **位置**：`test_completion.py:132-151` · 意图由函数名推断

#### 15. `test_install_repl_readline_completer`

- **意图**：覆盖: install repl readline completer
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`result in (True, False)`
- **位置**：`test_completion.py:154-157` · 意图由函数名推断

#### 16. `test_complete_chat_provider_flags`

- **意图**：覆盖: complete chat provider flags
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'--provider' in hits; '--session-id' in hits`
- **位置**：`test_completion.py:160-163` · 意图由函数名推断

#### 17. `test_complete_chat_provider_values`

- **意图**：覆盖: complete chat provider values
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`hits == ['ollama']`
- **位置**：`test_completion.py:166-168` · 意图由函数名推断

#### 18. `test_complete_memory_query_flags`

- **意图**：覆盖: complete memory query flags
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'--sort' in hits; '--tag' in hits; '--list-tags' in hits`
- **位置**：`test_completion.py:171-175` · 意图由函数名推断

#### 19. `test_complete_memory_query_sort_values`

- **意图**：覆盖: complete memory query sort values
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`hits == ['newest', 'oldest', 'relevance']; suggest_completions(['LA', 'memory', 'query', '--sort', 're'], build_parser()) == ['relevance']`
- **位置**：`test_completion.py:178-183` · 意图由函数名推断

#### 20. `test_complete_memory_query_tag_values`

- **意图**：覆盖: complete memory query tag values
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`hits == ['偏好', '家庭', '工作']; suggest_completions(['LA', 'memory', 'query', '--tag', '家'], build_parser()) == ['家庭']`
- **位置**：`test_completion.py:186-193` · 意图由函数名推断

#### 21. `test_session_slash_tab_memory_query_options`

- **意图**：覆盖: session slash tab memory query options
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'--sort' in hits; '--tag' in hits; suggest_session_slash_completions('/memory query --sort ', text='') == ['newest', 'oldest', 'relevance']; suggest_session_slash_completions('/memory query --sort re', text='re') == ['relevance']`
- **位置**：`test_completion.py:196-205` · 意图由函数名推断

#### 22. `test_complete_tasks_actions`

- **意图**：覆盖: complete tasks actions
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'pause' in hits`
- **位置**：`test_completion.py:208-210` · 意图由函数名推断

#### 23. `test_complete_cli_entry`

- **意图**：覆盖: complete cli entry
- **输入**：无外部夹具
- **方法**：CLI/subprocess
- **校验**：`rc == 0`
- **位置**：`test_completion.py:213-215` · 意图由函数名推断

#### 24. `test_complete_install_zsh`

- **意图**：覆盖: complete install zsh
- **输入**：夹具: capsys
- **方法**：CLI/subprocess + stdout
- **校验**：`rc == 0; 'compdef _la LA la' in out; 'compinit -C' in out; 'autoload -Uz compinit' in out`
- **位置**：`test_completion.py:218-224` · 意图由函数名推断

#### 25. `test_complete_init_writes_zshrc`

- **意图**：覆盖: complete init writes zshrc
- **输入**：夹具: tmp_path, monkeypatch
- **方法**：monkeypatch + CLI/subprocess + temp data
- **校验**：`rc == 0; '# >>> LA CLI completion >>>' in text; 'compdef _la LA la' in text`
- **位置**：`test_completion.py:227-236` · 意图由函数名推断

#### 26. `test_venv_activate_hook_patches_activate`

- **意图**：覆盖: venv activate hook patches activate
- **输入**：夹具: tmp_path, monkeypatch
- **方法**：monkeypatch + temp data
- **校验**：`(venv / 'activate.d' / 'la-completion.zsh').is_file(); (venv / 'activate.d' / 'la-completion.bash').is_file(); activate in hooks; '# >>> LA CLI completion >>>' in text; 'activate.d/la-completion.zsh' in text`
- **位置**：`test_completion.py:239-260` · 意图由函数名推断

#### 27. `test_ensure_shell_completion_silent`

- **意图**：覆盖: ensure shell completion silent
- **输入**：夹具: tmp_path, monkeypatch, capsys
- **方法**：monkeypatch + stdout + temp data
- **校验**：`out == ''; 'compdef _la LA la' in (tmp_path / '.zshrc').read_text(encoding='utf-8')`
- **位置**：`test_completion.py:263-272` · 意图由函数名推断


### `test_session_commands.py`（18）

#### 1. `test_is_session_command_slash_and_colon`

- **意图**：覆盖: is session command slash and colon
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`is_session_command('/help'); is_session_command(':provider ollama'); is_session_command('  /search foo'); not is_session_command('search foo'); not is_session_command('你好')`
- **位置**：`test_session_commands.py:21-26` · 意图由函数名推断

#### 2. `test_normalize_session_argv_aliases_and_quotes`

- **意图**：覆盖: normalize session argv aliases and quotes
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`normalize_session_argv('/add "hello world"') == ['memory', 'add', 'hello world']; normalize_session_argv(':p ollama') == ['provider', 'ollama']; normalize_session_argv('/q') == ['q']; normalize_session_argv('/h') == ['help']; normalize_session_argv('/model qwen3.5:4b') == ['model', 'qwen3.5:4b']`
- **位置**：`test_session_commands.py:29-36` · 意图由函数名推断

#### 3. `test_is_meta_user_content`

- **意图**：覆盖: is meta user content
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`is_meta_user_content('/deepsearch foo'); is_meta_user_content(':provider ollama'); not is_meta_user_content('普通对话')`
- **位置**：`test_session_commands.py:39-42` · 意图由函数名推断

#### 4. `test_dispatch_rejects_chat_in_session`

- **意图**：覆盖: dispatch rejects chat in session
- **输入**：夹具: capsys
- **方法**：stdout
- **校验**：`rc == 1; '无需 /chat' in capsys.readouterr().out`
- **位置**：`test_session_commands.py:45-48` · 意图由函数名推断

#### 5. `test_dispatch_session_unknown_goes_to_argparse`

- **意图**：覆盖: dispatch session unknown goes to argparse
- **输入**：夹具: capsys
- **方法**：stdout
- **校验**：`result.handled; result.exit_code != 0; result.exit_code == 2 or 'error' in out.lower() or 'invalid' in out.lower() or (out != '')`
- **位置**：`test_session_commands.py:51-58` · 意图由函数名推断

#### 6. `test_dispatch_session_help`

- **意图**：覆盖: dispatch session help
- **输入**：夹具: capsys
- **方法**：stdout
- **校验**：`result.exit_code == 0; 'add' in out; 'memory' in out; '/provider' in out; '/model' in out`
- **位置**：`test_session_commands.py:61-76` · 意图由函数名推断

#### 7. `test_dispatch_session_bare_memory_and_rag`

- **意图**：覆盖: dispatch session bare memory and rag
- **输入**：夹具: capsys
- **方法**：stdout
- **校验**：`mem.exit_code == 0; '[memory status]' in out; '来源分布' in out; rag.exit_code == 0; '[rag status]' in out`
- **位置**：`test_session_commands.py:79-91` · 意图由函数名推断

#### 8. `test_dispatch_session_model_list_and_set`

- **意图**：覆盖: dispatch session model list and set
- **输入**：夹具: monkeypatch, capsys, tmp_path
- **方法**：monkeypatch + stdout + temp data
- **校验**：`listed.exit_code == 0; '第 1/1 页' in out; 'qwen3.5:4b' in out; 'llama3.2:3b' in out; set_by_name.exit_code == 0`
- **位置**：`test_session_commands.py:94-135` · 意图由函数名推断

#### 9. `test_dispatch_session_model_pagination`

- **意图**：覆盖: dispatch session model pagination
- **输入**：夹具: monkeypatch, capsys
- **方法**：monkeypatch + stdout
- **校验**：`dispatch_session_line('/model', ctx).exit_code == 0; '第 1/3 页' in out; 'model-01' in out; 'model-10' in out; 'model-11' not in out`
- **位置**：`test_session_commands.py:138-185` · 意图由函数名推断

#### 10. `test_dispatch_session_rejects_ambiguous_m`

- **意图**：覆盖: dispatch session rejects ambiguous m
- **输入**：夹具: capsys
- **方法**：stdout
- **校验**：`result.exit_code == 1; '/m 已弃用' in out; '/model' in out; '/memory query' in out; '/mem' not in out.replace('/memory', '')`
- **位置**：`test_session_commands.py:188-196` · 意图由函数名推断

#### 11. `test_dispatch_session_exit`

- **意图**：覆盖: dispatch session exit
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`dispatch_session_line('/q', ctx).should_exit; dispatch_session_line(':quit', ctx).should_exit; dispatch_session_line('/exit', ctx).should_exit`
- **位置**：`test_session_commands.py:199-203` · 意图由函数名推断

#### 12. `test_chat_slash_search_does_not_call_agent`

- **意图**：覆盖: chat slash search does not call agent
- **输入**：夹具: monkeypatch, isolated_data, capsys
- **方法**：monkeypatch + mock + stdout + temp data
- **校验**：`'search' in out.lower() or '记忆' in out or '相关' in out or ('找到' in out) or ('未' in out)`
- **位置**：`test_session_commands.py:206-220` · 意图由函数名推断

#### 13. `test_chat_slash_add_does_not_call_agent`

- **意图**：覆盖: chat slash add does not call agent
- **输入**：夹具: monkeypatch, isolated_data
- **方法**：monkeypatch + mock + temp data
- **校验**：`get_memory_store().count() == before + 1; any(('slash 写入一条测试记忆' in t for t in texts))`
- **位置**：`test_session_commands.py:223-240` · 意图由函数名推断

#### 14. `test_chat_slash_provider_and_quit`

- **意图**：覆盖: chat slash provider and quit
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch + mock
- **校验**：`mock_turn.call_args.kwargs['provider'] == 'ollama'`
- **位置**：`test_session_commands.py:243-256` · 意图由函数名推断

#### 15. `test_chat_slash_deepsearch`

- **意图**：覆盖: chat slash deepsearch
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch + mock
- **校验**：`len(messages) == 2; messages[0]['content'].startswith('/deepsearch'); messages[1].get('tool') == 'deepsearch'`
- **位置**：`test_session_commands.py:259-273` · 意图由函数名推断

#### 16. `test_chat_colon_deepsearch_still_works`

- **意图**：Legacy :deepsearch remains a compatible alias.
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch + mock
- **校验**：`len(messages) == 2; 'deepsearch' in messages[0]['content']; messages[1].get('tool') == 'deepsearch'`
- **位置**：`test_session_commands.py:276-291` · 有 docstring

#### 17. `test_extract_skips_slash_commands`

- **意图**：覆盖: extract skips slash commands
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`extract_session_memories(session_id, interactive=False) == []`
- **位置**：`test_session_commands.py:294-304` · 意图由函数名推断

#### 18. `test_outer_cli_still_dispatches_add`

- **意图**：覆盖: outer cli still dispatches add
- **输入**：夹具: isolated_data, capsys
- **方法**：mock + CLI/subprocess + stdout + temp data
- **校验**：`rc == 0`
- **位置**：`test_session_commands.py:307-314` · 意图由函数名推断


### `test_ui.py`（12）

#### 1. `test_emit`

- **意图**：覆盖: emit
- **输入**：夹具: capsys
- **方法**：stdout
- **校验**：`capsys.readouterr().out == '[test] hello\n'`
- **位置**：`test_ui.py:13-15` · 意图由函数名推断

#### 2. `test_read_repl_line_passes_prompt_to_input`

- **意图**：Prompt must go through input() so backspace cannot erase ``>``.
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`read_repl_line('> ') == 'hello'; seen == ['> ']`
- **位置**：`test_ui.py:18-28` · 有 docstring

#### 3. `test_spinner_non_tty`

- **意图**：覆盖: spinner non tty
- **输入**：夹具: capsys
- **方法**：stdout
- **校验**：`'[sync] working' in out`
- **位置**：`test_ui.py:31-35` · 意图由函数名推断

#### 4. `test_activity_indicator_update`

- **意图**：覆盖: activity indicator update
- **输入**：夹具: capsys
- **方法**：stdout
- **校验**：`'[chat] 思考中…' in out; '[chat] 调用工具: search_memory' in out; '\r' not in out; '\x1b[2K' not in out`
- **位置**：`test_ui.py:38-45` · 意图由函数名推断

#### 5. `test_activity_indicator_streaming`

- **意图**：覆盖: activity indicator streaming
- **输入**：夹具: capsys
- **方法**：stdout
- **校验**：`'streamed' in out; '\r' not in out; '\x1b[2K' not in out`
- **位置**：`test_ui.py:48-56` · 意图由函数名推断

#### 6. `test_activity_indicator_exit`

- **意图**：覆盖: activity indicator exit
- **输入**：夹具: capsys
- **方法**：stdout
- **校验**：`'[chat] ✓' in out; out.endswith('\n'); '\r' not in out`
- **位置**：`test_ui.py:59-65` · 意图由函数名推断

#### 7. `test_render_welcome_shows_project_basics`

- **意图**：覆盖: render welcome shows project basics
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`f'LocalAgent v{__version__}' in out; 'LOCAL' in out and 'AGENT' in out; 'Your AI. Your Data. Your Machine.' in out; 'qwen3.5:4b' in out; '联网 · ddgs（免费）' in out`
- **位置**：`test_ui.py:68-96` · 意图由函数名推断

#### 8. `test_format_web_search_hint_tavily_when_key_set`

- **意图**：覆盖: format web search hint tavily when key set
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`format_web_search_hint() == '联网 · Tavily'`
- **位置**：`test_ui.py:99-103` · 意图由函数名推断

#### 9. `test_format_web_search_hint_ddgs_without_key`

- **意图**：覆盖: format web search hint ddgs without key
- **输入**：夹具: monkeypatch
- **方法**：monkeypatch
- **校验**：`format_web_search_hint() == '联网 · ddgs（免费）'`
- **位置**：`test_ui.py:106-110` · 意图由函数名推断

#### 10. `test_collect_welcome_info_includes_web_search`

- **意图**：覆盖: collect welcome info includes web search
- **输入**：夹具: monkeypatch, tmp_path
- **方法**：monkeypatch + mock + temp data
- **校验**：`info.web_search_line == '联网 · Tavily'`
- **位置**：`test_ui.py:113-125` · 意图由函数名推断

#### 11. `test_cli_bare_la_defaults_to_chat`

- **意图**：覆盖: cli bare la defaults to chat
- **输入**：无外部夹具
- **方法**：mock + CLI/subprocess
- **校验**：`rc == 0; kwargs.get('provider') == 'auto'; kwargs.get('session_id') is None`
- **位置**：`test_ui.py:128-141` · 意图由函数名推断

#### 12. `test_chat_repl_prints_welcome`

- **意图**：覆盖: chat repl prints welcome
- **输入**：夹具: capsys, monkeypatch, tmp_path
- **方法**：monkeypatch + mock + stdout + temp data
- **校验**：`'LocalAgent v' in out; '项目状态' in out; 's-welcome' in out`
- **位置**：`test_ui.py:144-167` · 意图由函数名推断


### `test_workspace.py`（5）

#### 1. `test_scan_todos_finds_markers`

- **意图**：覆盖: scan todos finds markers
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`'fix login bug' in texts; '完成 Phase 1' in texts`
- **位置**：`test_workspace.py:16-27` · 意图由函数名推断

#### 2. `test_recent_files_lists_modified`

- **意图**：覆盖: recent files lists modified
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`any((f['path'] == 'changed.txt' for f in files))`
- **位置**：`test_workspace.py:30-34` · 意图由函数名推断

#### 3. `test_git_summary_non_repo`

- **意图**：覆盖: git summary non repo
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`summary.is_repo is False; '不是 git 仓库' in summary.to_text()`
- **位置**：`test_workspace.py:37-40` · 意图由函数名推断

#### 4. `test_format_workspace_summary_includes_sections`

- **意图**：覆盖: format workspace summary includes sections
- **输入**：夹具: tmp_path, monkeypatch
- **方法**：monkeypatch + temp data
- **校验**：`'工作区:' in text; '待办' in text or 'task.md' in text`
- **位置**：`test_workspace.py:43-49` · 意图由函数名推断

#### 5. `test_cli_workspace_command`

- **意图**：覆盖: cli workspace command
- **输入**：夹具: tmp_path, capsys
- **方法**：CLI/subprocess + stdout + temp data
- **校验**：`rc == 0; 'cli test' in out`
- **位置**：`test_workspace.py:52-57` · 意图由函数名推断


## Audit

### `test_audit.py`（8）

#### 1. `test_log_and_aggregate_usage`

- **意图**：覆盖: log and aggregate usage
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`len(events) == 2; stats['total_calls'] == 2; stats['total_tokens'] == 430; 'ollama' in stats['by_provider']`
- **位置**：`test_audit.py:14-22` · 意图由函数名推断

#### 2. `test_parse_since`

- **意图**：覆盖: parse since
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`since is not None`
- **位置**：`test_audit.py:25-27` · 意图由函数名推断

#### 3. `test_security_scan_flags_env_symlink`

- **意图**：覆盖: security scan flags env symlink
- **输入**：夹具: tmp_path, isolated_data, monkeypatch
- **方法**：monkeypatch + temp data
- **校验**：`report.high_count >= 1; any(('.env' in f.path for f in report.findings))`
- **位置**：`test_audit.py:30-38` · 意图由函数名推断

#### 4. `test_memory_health_counts`

- **意图**：覆盖: memory health counts
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`health.memory_facts == 0`
- **位置**：`test_audit.py:41-43` · 意图由函数名推断

#### 5. `test_generate_report`

- **意图**：覆盖: generate report
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`'# LocalAgent 审计报告' in md; 'Token 与服务花费' in md; 'Agent 行为与护栏' in md; '文件安全' in md`
- **位置**：`test_audit.py:46-52` · 意图由函数名推断

#### 6. `test_log_event_and_behavior_in_cli`

- **意图**：覆盖: log event and behavior in cli
- **输入**：夹具: isolated_data, capsys
- **方法**：CLI/subprocess + stdout + temp data
- **校验**：`rc == 0; 'shell=1' in out; 'web=1' in out`
- **位置**：`test_audit.py:55-76` · 意图由函数名推断

#### 7. `test_cli_audit_summary`

- **意图**：覆盖: cli audit summary
- **输入**：夹具: isolated_data, capsys
- **方法**：CLI/subprocess + stdout + temp data
- **校验**：`rc == 0; '[audit]' in out; 'Token' in out`
- **位置**：`test_audit.py:79-85` · 意图由函数名推断

#### 8. `test_cli_audit_report_file`

- **意图**：覆盖: cli audit report file
- **输入**：夹具: isolated_data, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`rc == 0; out.is_file(); '审计报告' in out.read_text(encoding='utf-8')`
- **位置**：`test_audit.py:88-93` · 意图由函数名推断


### `test_audit_guardrails.py`（12）

#### 1. `test_classify_blocks_destructive_commands`

- **意图**：覆盖: classify blocks destructive commands
- **输入**：参数: command, reason_substr
- **方法**：parametrize
- **校验**：`risk.level == 'blocked'; reason_substr in (risk.reason or '')`
- **位置**：`test_audit_guardrails.py:30-33` · 意图由函数名推断

#### 2. `test_classify_marks_dangerous_but_not_blocked`

- **意图**：覆盖: classify marks dangerous but not blocked
- **输入**：参数: command
- **方法**：parametrize
- **校验**：`risk.level == 'dangerous'`
- **位置**：`test_audit_guardrails.py:45-47` · 意图由函数名推断

#### 3. `test_run_shell_never_executes_blocked_command`

- **意图**：覆盖: run shell never executes blocked command
- **输入**：夹具: isolated_data
- **方法**：mock + temp data + parametrize
- **校验**：`'禁止' in out or '错误' in out`
- **位置**：`test_audit_guardrails.py:50-54` · 意图由函数名推断

#### 4. `test_agent_blocks_rm_rf_root_without_executing`

- **意图**：覆盖: agent blocks rm rf root without executing
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + mock + temp data
- **校验**：`result.tool_calls; blocked; blocked[0]['tool'] == 'run_shell'; any((e.get('type') == 'guardrail.triggered' for e in events))`
- **位置**：`test_audit_guardrails.py:57-75` · 意图由函数名推断

#### 5. `test_agent_denies_dangerous_rm_and_logs`

- **意图**：覆盖: agent denies dangerous rm and logs
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + mock + temp data
- **校验**：`asked; denied`
- **位置**：`test_audit_guardrails.py:78-105` · 意图由函数名推断

#### 6. `test_agent_executes_safe_shell_when_approval_off`

- **意图**：覆盖: agent executes safe shell when approval off
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + mock + temp data
- **校验**：`executed; executed[0]['tool'] == 'run_shell'`
- **位置**：`test_audit_guardrails.py:108-124` · 意图由函数名推断

#### 7. `test_write_file_is_dangerous`

- **意图**：覆盖: write file is dangerous
- **输入**：夹具: isolated_data
- **方法**：temp data
- **校验**：`risk.level == 'dangerous'`
- **位置**：`test_audit_guardrails.py:127-129` · 意图由函数名推断

#### 8. `test_prepare_symlink_blocks_env_file`

- **意图**：覆盖: prepare symlink blocks env file
- **输入**：夹具: tmp_path, isolated_data
- **方法**：temp data + raises
- **校验**：`not (isolated_data['kb_dir'] / '.env').exists(); any((e.get('type') == 'kb.blocked' for e in events)); any((e.get('type') == 'guardrail.triggered' for e in events))`
- **位置**：`test_audit_guardrails.py:132-140` · 意图由函数名推断

#### 9. `test_prepare_symlink_blocks_pem`

- **意图**：覆盖: prepare symlink blocks pem
- **输入**：夹具: tmp_path, isolated_data
- **方法**：temp data + raises
- **校验**：`(隐式/副作用校验)`
- **位置**：`test_audit_guardrails.py:143-147` · 意图由函数名推断

#### 10. `test_ingest_file_blocks_sensitive_even_if_already_in_kb`

- **意图**：覆盖: ingest file blocks sensitive even if already in kb
- **输入**：夹具: tmp_path, isolated_data
- **方法**：temp data
- **校验**：`is_sensitive_path(link); result.status == IngestStatus.FAILED; '敏感' in result.error; any((e.get('type') == 'kb.blocked' for e in load_events()))`
- **位置**：`test_audit_guardrails.py:150-160` · 意图由函数名推断

#### 11. `test_security_scan_still_flags_existing_env_symlink`

- **意图**：覆盖: security scan still flags existing env symlink
- **输入**：夹具: tmp_path, isolated_data
- **方法**：temp data
- **校验**：`report.high_count >= 1`
- **位置**：`test_audit_guardrails.py:163-169` · 意图由函数名推断

#### 12. `test_audit_report_includes_blocked_behavior`

- **意图**：覆盖: audit report includes blocked behavior
- **输入**：夹具: isolated_data, monkeypatch
- **方法**：monkeypatch + mock + temp data
- **校验**：`behavior['outcomes'].get('blocked', 0) >= 1; behavior['guardrail_triggers'] >= 1; 'Agent 行为与护栏' in md; '本周期拦截' in md; '护栏=' in summary`
- **位置**：`test_audit_guardrails.py:172-194` · 意图由函数名推断


## E2E

### `e2e/test_la_commands.py`（14）

#### 1. `test_e2e_help`

- **意图**：覆盖: e2e help
- **输入**：无外部夹具
- **方法**：CLI/subprocess
- **校验**：`result.returncode == 0; 'memory' in result.stdout; 'rag' in result.stdout; 'chat' in result.stdout; 'tasks' in result.stdout`
- **位置**：`e2e/test_la_commands.py:17-24` · 意图由函数名推断

#### 2. `test_e2e_add`

- **意图**：覆盖: e2e add
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '已写入记忆' in result.stdout`
- **位置**：`e2e/test_la_commands.py:27-30` · 意图由函数名推断

#### 3. `test_e2e_add_rejects_short_text`

- **意图**：覆盖: e2e add rejects short text
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 1; '未写入' in result.stdout`
- **位置**：`e2e/test_la_commands.py:33-36` · 意图由函数名推断

#### 4. `test_e2e_rag_add_and_ingest`

- **意图**：覆盖: e2e rag add and ingest
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '软链:' in result.stdout; 'done' in result.stdout; kb_link.is_symlink(); result2.returncode == 0`
- **位置**：`e2e/test_la_commands.py:39-56` · 意图由函数名推断

#### 5. `test_e2e_rag_ingest_force`

- **意图**：覆盖: e2e rag ingest force
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'updated' in result.stdout or 'new' in result.stdout or 'rag ingest' in result.stdout`
- **位置**：`e2e/test_la_commands.py:59-66` · 意图由函数名推断

#### 6. `test_e2e_search_memory`

- **意图**：覆盖: e2e search memory
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'Mem0' in result.stdout; 'forget' in result.stdout`
- **位置**：`e2e/test_la_commands.py:69-74` · 意图由函数名推断

#### 7. `test_e2e_search_knowledge`

- **意图**：覆盖: e2e search knowledge
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'Mem0' in result.stdout`
- **位置**：`e2e/test_la_commands.py:77-84` · 意图由函数名推断

#### 8. `test_e2e_forget_memory`

- **意图**：覆盖: e2e forget memory
- **输入**：夹具: la_env, la_data_dir
- **方法**：CLI/subprocess + temp data
- **校验**：`search.returncode == 0; fact_id[:8] in search.stdout; forget.returncode == 0; '已删除' in forget.stdout`
- **位置**：`e2e/test_la_commands.py:87-98` · 意图由函数名推断

#### 9. `test_e2e_reset_memory`

- **意图**：覆盖: e2e reset memory
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'memory reset' in result.stdout; (Path(la_env['LA_DATA_DIR']) / 'kb' / 'doc.md').exists()`
- **位置**：`e2e/test_la_commands.py:101-110` · 意图由函数名推断

#### 10. `test_e2e_rag_rebuild`

- **意图**：覆盖: e2e rag rebuild
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'rag rebuild' in result.stdout`
- **位置**：`e2e/test_la_commands.py:113-121` · 意图由函数名推断

#### 11. `test_e2e_ollama_model_autodetect`

- **意图**：覆盖: e2e ollama model autodetect
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`proc.returncode == 0; resolved in ollama_completion_models()`
- **位置**：`e2e/test_la_commands.py:124-151` · 意图由函数名推断

#### 12. `test_e2e_add_file_background`

- **意图**：覆盖: e2e add file background
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '后台任务' in result.stdout; '软链:' in result.stdout; '日志:' in result.stdout; status.returncode == 0`
- **位置**：`e2e/test_la_commands.py:154-169` · 意图由函数名推断

#### 13. `test_e2e_tasks_list`

- **意图**：覆盖: e2e tasks list
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 't-' in result.stdout`
- **位置**：`e2e/test_la_commands.py:172-179` · 意图由函数名推断

#### 14. `test_mem0_is_core_dependency`

- **意图**：mem0ai is a required dependency for the Warm memory engine.
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`'mem0ai' in text; 'hindsight-all' not in text`
- **位置**：`e2e/test_la_commands.py:182-186` · 有 docstring


### `e2e/test_la_completion.py`（6）

#### 1. `test_e2e_complete_memory_prefix`

- **意图**：覆盖: e2e complete memory prefix
- **输入**：无外部夹具
- **方法**：CLI/subprocess
- **校验**：`result.returncode == 0; lines == ['memory']`
- **位置**：`e2e/test_la_completion.py:33-37` · 意图由函数名推断

#### 2. `test_e2e_complete_all_commands`

- **意图**：覆盖: e2e complete all commands
- **输入**：无外部夹具
- **方法**：CLI/subprocess
- **校验**：`result.returncode == 0; {'chat', 'memory', 'tasks'}.issubset(lines)`
- **位置**：`e2e/test_la_completion.py:40-44` · 意图由函数名推断

#### 3. `test_e2e_complete_chat_provider_flag`

- **意图**：覆盖: e2e complete chat provider flag
- **输入**：无外部夹具
- **方法**：CLI/subprocess
- **校验**：`result.returncode == 0; '--provider' in result.stdout`
- **位置**：`e2e/test_la_completion.py:47-50` · 意图由函数名推断

#### 4. `test_e2e_zsh_compdef_registers_la`

- **意图**：覆盖: e2e zsh compdef registers la
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`result.returncode == 0; 'compdef_ok' in result.stdout`
- **位置**：`e2e/test_la_completion.py:55-60` · 意图由函数名推断

#### 5. `test_e2e_zsh_la_memory_tab_candidates`

- **意图**：Simulate LA mem<Tab>: _la should offer memory.
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`result.returncode == 0; lines == ['memory']`
- **位置**：`e2e/test_la_completion.py:65-75` · 有 docstring

#### 6. `test_e2e_complete_init_writes_block`

- **意图**：Run complete-init in isolation (non-macOS CI only).
- **输入**：夹具: tmp_path
- **方法**：temp data
- **校验**：`result.returncode == 0; 'compinit -C' in text; 'compdef _la LA la' in text`
- **位置**：`e2e/test_la_completion.py:79-99` · 有 docstring


### `e2e/test_la_live.py`（5）

#### 1. `test_e2e_rememorize_chat`

- **意图**：覆盖: e2e rememorize chat
- **输入**：夹具: la_env, la_data_dir
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '已保存' in result.stdout or '未提取' in result.stdout`
- **位置**：`e2e/test_la_live.py:18-34` · 意图由函数名推断

#### 2. `test_e2e_chat_live`

- **意图**：覆盖: e2e chat live
- **输入**：夹具: la_env, la_data_dir
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'all model providers failed' not in result.stdout; '[错误]' not in result.stdout; conv.exists(); len(messages) >= 2`
- **位置**：`e2e/test_la_live.py:37-60` · 意图由函数名推断

#### 3. `test_e2e_live_memory_search_semantic`

- **意图**：覆盖: e2e live memory search semantic
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'Mem0' in result.stdout`
- **位置**：`e2e/test_la_live.py:63-68` · 意图由函数名推断

#### 4. `test_e2e_live_memory_reflect_multihop`

- **意图**：覆盖: e2e live memory reflect multihop
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '未能从记忆中推理出答案' not in result.stdout; 'Mem0' in result.stdout or '徒步' in result.stdout`
- **位置**：`e2e/test_la_live.py:71-83` · 意图由函数名推断

#### 5. `test_e2e_live_rag_search_after_add`

- **意图**：覆盖: e2e live rag search after add
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`run_la(['rag', 'add', str(doc)], env=la_env, timeout=180).returncode == 0; result.returncode == 0; 'Chroma' in result.stdout or 'BM25' in result.stdout or 'Cold' in result.stdout`
- **位置**：`e2e/test_la_live.py:86-93` · 意图由函数名推断


### `e2e/test_la_memory.py`（35）

#### 1. `test_e2e_memory_help`

- **意图**：覆盖: e2e memory help
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; token in result.stdout`
- **位置**：`e2e/test_la_memory.py:27-31` · 意图由函数名推断

#### 2. `test_e2e_bare_memory_shows_status`

- **意图**：覆盖: e2e bare memory shows status
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '[memory status]' in result.stdout; '来源分布' in result.stdout; '下一步' in result.stdout`
- **位置**：`e2e/test_la_memory.py:34-39` · 意图由函数名推断

#### 3. `test_e2e_memory_add_and_status`

- **意图**：覆盖: e2e memory add and status
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`status.returncode == 0; 'Warm' in status.stdout; 'json' in status.stdout; '记忆条数' in status.stdout; '1' in status.stdout`
- **位置**：`e2e/test_la_memory.py:42-49` · 意图由函数名推断

#### 4. `test_e2e_memory_search_hit_and_miss`

- **意图**：覆盖: e2e memory search hit and miss
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`hit.returncode == 0; 'Mem0' in hit.stdout; 'forget' in hit.stdout; miss.returncode == 0; '[错误]' not in miss.stdout`
- **位置**：`e2e/test_la_memory.py:52-62` · 意图由函数名推断

#### 5. `test_e2e_memory_search_top_k_and_verbose`

- **意图**：覆盖: e2e memory search top k and verbose
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; result.stdout.strip()`
- **位置**：`e2e/test_la_memory.py:65-70` · 意图由函数名推断

#### 6. `test_e2e_memory_search_knowledge_flag_migrated`

- **意图**：覆盖: e2e memory search knowledge flag migrated
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 2; 'rag search' in result.stdout`
- **位置**：`e2e/test_la_memory.py:73-76` · 意图由函数名推断

#### 7. `test_e2e_memory_query_list_json_and_tags`

- **意图**：覆盖: e2e memory query list json and tags
- **输入**：夹具: la_env, la_data_dir
- **方法**：CLI/subprocess + temp data
- **校验**：`listed.returncode == 0; 'Mem0' in listed.stdout or '葡萄酒' in listed.stdout; 'forget' in listed.stdout; as_json.returncode == 0; isinstance(payload, list)`
- **位置**：`e2e/test_la_memory.py:79-101` · 意图由函数名推断

#### 8. `test_e2e_memory_query_since_until`

- **意图**：覆盖: e2e memory query since until
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; isinstance(payload, list)`
- **位置**：`e2e/test_la_memory.py:104-112` · 意图由函数名推断

#### 9. `test_e2e_memory_forget_missing_and_cancel`

- **意图**：覆盖: e2e memory forget missing and cancel
- **输入**：夹具: la_env, la_data_dir
- **方法**：CLI/subprocess + temp data
- **校验**：`missing.returncode == 1; '未找到' in missing.stdout; cancel.returncode == 0; '已取消' in cancel.stdout; memory_fact_ids(la_data_dir) == [fact_id]`
- **位置**：`e2e/test_la_memory.py:115-125` · 意图由函数名推断

#### 10. `test_e2e_memory_reset_by_source`

- **意图**：覆盖: e2e memory reset by source
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'memory reset' in result.stdout; 'done' in result.stdout; '记忆条数' in status.stdout`
- **位置**：`e2e/test_la_memory.py:128-136` · 意图由函数名推断

#### 11. `test_e2e_memory_reset_file_migrated`

- **意图**：覆盖: e2e memory reset file migrated
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 2; 'rag reset' in result.stdout`
- **位置**：`e2e/test_la_memory.py:139-142` · 意图由函数名推断

#### 12. `test_e2e_memory_rebuild_points_to_reindex`

- **意图**：覆盖: e2e memory rebuild points to reindex
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 2; 'reindex' in result.stdout; 'rag rebuild' in result.stdout`
- **位置**：`e2e/test_la_memory.py:145-149` · 意图由函数名推断

#### 13. `test_e2e_memory_reindex_json_backend`

- **意图**：覆盖: e2e memory reindex json backend
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'memory reindex' in result.stdout; 'json' in result.stdout.lower() or 'skipped' in result.stdout.lower() or 'reindexed' in result.stdout`
- **位置**：`e2e/test_la_memory.py:152-157` · 意图由函数名推断

#### 14. `test_e2e_memory_add_file_migrated`

- **意图**：覆盖: e2e memory add file migrated
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 2; 'rag add' in result.stdout`
- **位置**：`e2e/test_la_memory.py:160-165` · 意图由函数名推断

#### 15. `test_e2e_memory_ingest_chat_empty_session`

- **意图**：Without LLM extraction success, command still exits cleanly.
- **输入**：夹具: la_env, la_data_dir
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '已保存' in result.stdout or '未提取' in result.stdout`
- **位置**：`e2e/test_la_memory.py:168-179` · 有 docstring

#### 16. `test_e2e_memory_ingest_chatgpt_file`

- **意图**：覆盖: e2e memory ingest chatgpt file
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'chatgpt' in result.stdout.lower() or '记忆' in result.stdout or '未' in result.stdout`
- **位置**：`e2e/test_la_memory.py:182-192` · 意图由函数名推断

#### 17. `test_e2e_memory_consolidate_foreground`

- **意图**：覆盖: e2e memory consolidate foreground
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'memory consolidate' in result.stdout; 'changed=' in result.stdout`
- **位置**：`e2e/test_la_memory.py:195-205` · 意图由函数名推断

#### 18. `test_e2e_memory_consolidate_background`

- **意图**：覆盖: e2e memory consolidate background
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '后台任务' in result.stdout`
- **位置**：`e2e/test_la_memory.py:208-214` · 意图由函数名推断

#### 19. `test_e2e_memory_reflect_smoke`

- **意图**：Offline-safe: command returns; may synthesize or report inability.
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '推理记忆' in result.stdout or result.stdout.strip(); '[错误]' not in result.stdout`
- **位置**：`e2e/test_la_memory.py:217-223` · 有 docstring

#### 20. `test_e2e_memory_reflect_with_evidence`

- **意图**：When a completion model is available, reflect should use seeded facts.
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '未能从记忆中推理出答案' not in out or 'Mem0' in out or '葡萄酒' in out; 'Mem0' in out or '葡萄酒' in out or '记忆' in out`
- **位置**：`e2e/test_la_memory.py:226-241` · 有 docstring

#### 21. `test_e2e_memory_roundtrip_add_search_forget`

- **意图**：覆盖: e2e memory roundtrip add search forget
- **输入**：夹具: la_env, la_data_dir
- **方法**：CLI/subprocess + temp data
- **校验**：`search.returncode == 0; fact_id[:8] in search.stdout; forget.returncode == 0; '已删除' in forget.stdout; after.returncode == 0`
- **位置**：`e2e/test_la_memory.py:244-257` · 意图由函数名推断

#### 22. `test_e2e_memory_status_empty_and_help`

- **意图**：覆盖: e2e memory status empty and help
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`status.returncode == 0; '记忆条数' in status.stdout; '来源分布' in status.stdout; help_.returncode == 0`
- **位置**：`e2e/test_la_memory.py:260-266` · 意图由函数名推断

#### 23. `test_e2e_memory_status_source_counts`

- **意图**：覆盖: e2e memory status source counts
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`status.returncode == 0; '记忆条数' in status.stdout; '1' in status.stdout; 'other=' in status.stdout or 'manual' in status.stdout.lower() or '来源分布' in status.stdout`
- **位置**：`e2e/test_la_memory.py:269-275` · 意图由函数名推断

#### 24. `test_e2e_memory_reindex_empty_store`

- **意图**：覆盖: e2e memory reindex empty store
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'memory reindex' in result.stdout`
- **位置**：`e2e/test_la_memory.py:278-281` · 意图由函数名推断

#### 25. `test_e2e_memory_reindex_idempotent`

- **意图**：覆盖: e2e memory reindex idempotent
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`first.returncode == 0; second.returncode == 0; 'memory reindex' in first.stdout; 'memory reindex' in second.stdout`
- **位置**：`e2e/test_la_memory.py:284-291` · 意图由函数名推断

#### 26. `test_e2e_memory_rebuild_help_message_stable`

- **意图**：覆盖: e2e memory rebuild help message stable
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 2; 'LA memory reindex' in result.stdout; 'LA rag rebuild' in result.stdout`
- **位置**：`e2e/test_la_memory.py:294-298` · 意图由函数名推断

#### 27. `test_e2e_memory_add_file_help_points_to_rag`

- **意图**：覆盖: e2e memory add file help points to rag
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`help_.returncode == 0; 'rag add' in help_.stdout; bare.returncode == 2; 'rag add' in bare.stdout`
- **位置**：`e2e/test_la_memory.py:301-307` · 意图由函数名推断

#### 28. `test_e2e_memory_consolidate_empty`

- **意图**：覆盖: e2e memory consolidate empty
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'changed=' in result.stdout`
- **位置**：`e2e/test_la_memory.py:310-317` · 意图由函数名推断

#### 29. `test_e2e_memory_consolidate_help`

- **意图**：覆盖: e2e memory consolidate help
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '--foreground' in result.stdout or '-f' in result.stdout; '--limit' in result.stdout`
- **位置**：`e2e/test_la_memory.py:320-324` · 意图由函数名推断

#### 30. `test_e2e_memory_query_limit_and_sort_oldest`

- **意图**：覆盖: e2e memory query limit and sort oldest
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; isinstance(payload, list); len(payload) <= 1`
- **位置**：`e2e/test_la_memory.py:327-334` · 意图由函数名推断

#### 31. `test_e2e_memory_query_verbose`

- **意图**：覆盖: e2e memory query verbose
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'Mem0' in result.stdout`
- **位置**：`e2e/test_la_memory.py:337-341` · 意图由函数名推断

#### 32. `test_e2e_memory_ingest_all_no_sessions`

- **意图**：覆盖: e2e memory ingest all no sessions
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0`
- **位置**：`e2e/test_la_memory.py:344-346` · 意图由函数名推断

#### 33. `test_e2e_memory_ingest_chat_force_flag`

- **意图**：覆盖: e2e memory ingest chat force flag
- **输入**：夹具: la_env, la_data_dir
- **方法**：CLI/subprocess + temp data
- **校验**：`first.returncode == 0; second.returncode == 0`
- **位置**：`e2e/test_la_memory.py:349-367` · 意图由函数名推断

#### 34. `test_e2e_memory_reflect_empty_bank`

- **意图**：覆盖: e2e memory reflect empty bank
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '未能从记忆中推理出答案' in result.stdout or result.stdout.strip()`
- **位置**：`e2e/test_la_memory.py:370-373` · 意图由函数名推断

#### 35. `test_e2e_memory_reflect_help`

- **意图**：覆盖: e2e memory reflect help
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'query' in result.stdout.lower() or '推理' in result.stdout`
- **位置**：`e2e/test_la_memory.py:376-379` · 意图由函数名推断


### `e2e/test_la_ops.py`（25）

#### 1. `test_e2e_version`

- **意图**：覆盖: e2e version
- **输入**：无外部夹具
- **方法**：CLI/subprocess
- **校验**：`result.returncode == 0; result.stdout.strip()`
- **位置**：`e2e/test_la_ops.py:15-18` · 意图由函数名推断

#### 2. `test_e2e_help_lists_core_commands`

- **意图**：覆盖: e2e help lists core commands
- **输入**：无外部夹具
- **方法**：CLI/subprocess
- **校验**：`result.returncode == 0; cmd in result.stdout`
- **位置**：`e2e/test_la_ops.py:21-25` · 意图由函数名推断

#### 3. `test_e2e_chat_help`

- **意图**：覆盖: e2e chat help
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '--session-id' in result.stdout; '--provider' in result.stdout`
- **位置**：`e2e/test_la_ops.py:28-32` · 意图由函数名推断

#### 4. `test_e2e_chat_invalid_provider`

- **意图**：覆盖: e2e chat invalid provider
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 1; 'invalid provider' in result.stdout.lower() or 'provider' in result.stdout.lower()`
- **位置**：`e2e/test_la_ops.py:35-38` · 意图由函数名推断

#### 5. `test_e2e_chat_quit_immediately`

- **意图**：Enter chat and quit without sending a model turn.
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode in (0, 1); '[错误]' not in result.stdout or 'provider' in result.stdout.lower()`
- **位置**：`e2e/test_la_ops.py:41-50` · 有 docstring

#### 6. `test_e2e_config_example`

- **意图**：覆盖: e2e config example
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'provider' in result.stdout; 'ollama' in result.stdout.lower() or 'TAVILY' in result.stdout`
- **位置**：`e2e/test_la_ops.py:53-57` · 意图由函数名推断

#### 7. `test_e2e_config_help`

- **意图**：覆盖: e2e config help
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'list' in result.stdout; 'add' in result.stdout or 'set-key' in result.stdout`
- **位置**：`e2e/test_la_ops.py:60-64` · 意图由函数名推断

#### 8. `test_e2e_config_list`

- **意图**：覆盖: e2e config list
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'ollama' in result.stdout.lower() or 'provider' in result.stdout.lower() or 'model' in result.stdout.lower()`
- **位置**：`e2e/test_la_ops.py:67-74` · 意图由函数名推断

#### 9. `test_e2e_config_remove_missing`

- **意图**：覆盖: e2e config remove missing
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 1; '未找到' in result.stdout or 'not' in result.stdout.lower() or 'config' in result.stdout.lower()`
- **位置**：`e2e/test_la_ops.py:77-80` · 意图由函数名推断

#### 10. `test_e2e_config_apply_missing_file`

- **意图**：覆盖: e2e config apply missing file
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode != 0`
- **位置**：`e2e/test_la_ops.py:83-86` · 意图由函数名推断

#### 11. `test_e2e_workspace_summary`

- **意图**：覆盖: e2e workspace summary
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; result.stdout.strip(); '[错误]' not in result.stdout`
- **位置**：`e2e/test_la_ops.py:89-93` · 意图由函数名推断

#### 12. `test_e2e_workspace_todos_only`

- **意图**：覆盖: e2e workspace todos only
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'workspace' in result.stdout.lower() or '待办' in result.stdout or 'TODO' in result.stdout`
- **位置**：`e2e/test_la_ops.py:96-101` · 意图由函数名推断

#### 13. `test_e2e_workspace_help`

- **意图**：覆盖: e2e workspace help
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '--days' in result.stdout; '--todos-only' in result.stdout or 'todos' in result.stdout`
- **位置**：`e2e/test_la_ops.py:104-108` · 意图由函数名推断

#### 14. `test_e2e_workspace_empty_todos`

- **意图**：覆盖: e2e workspace empty todos
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '未扫描' in result.stdout or '0' in result.stdout or '待办' in result.stdout`
- **位置**：`e2e/test_la_ops.py:111-116` · 意图由函数名推断

#### 15. `test_e2e_audit_summary`

- **意图**：覆盖: e2e audit summary
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; result.stdout.strip()`
- **位置**：`e2e/test_la_ops.py:119-122` · 意图由函数名推断

#### 16. `test_e2e_audit_invalid_since`

- **意图**：覆盖: e2e audit invalid since
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 1; 'audit' in result.stdout.lower() or result.stderr`
- **位置**：`e2e/test_la_ops.py:125-128` · 意图由函数名推断

#### 17. `test_e2e_audit_report_file`

- **意图**：覆盖: e2e audit report file
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '报告已写入' in result.stdout; out.is_file(); out.stat().st_size > 0`
- **位置**：`e2e/test_la_ops.py:131-137` · 意图由函数名推断

#### 18. `test_e2e_audit_help`

- **意图**：覆盖: e2e audit help
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '--since' in result.stdout; '--report' in result.stdout`
- **位置**：`e2e/test_la_ops.py:140-144` · 意图由函数名推断

#### 19. `test_e2e_setup_skip`

- **意图**：覆盖: e2e setup skip
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'setup' in result.stdout.lower() or '跳过' in result.stdout or 'skip' in result.stdout.lower()`
- **位置**：`e2e/test_la_ops.py:147-151` · 意图由函数名推断

#### 20. `test_e2e_setup_help`

- **意图**：覆盖: e2e setup help
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '--yes' in result.stdout or 'Ollama' in result.stdout or 'ollama' in result.stdout.lower()`
- **位置**：`e2e/test_la_ops.py:154-157` · 意图由函数名推断

#### 21. `test_e2e_setup_decline_prompt`

- **意图**：覆盖: e2e setup decline prompt
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '跳过' in result.stdout or 'setup' in result.stdout.lower() or 'declin' in result.stdout.lower()`
- **位置**：`e2e/test_la_ops.py:160-165` · 意图由函数名推断

#### 22. `test_e2e_tasks_help_and_empty_list`

- **意图**：覆盖: e2e tasks help and empty list
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`help_.returncode == 0; 'delete' in help_.stdout or 'pause' in help_.stdout or 'logs' in help_.stdout; listed.returncode == 0`
- **位置**：`e2e/test_la_ops.py:168-174` · 意图由函数名推断

#### 23. `test_e2e_tasks_unknown_id`

- **意图**：覆盖: e2e tasks unknown id
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 1; '未找到' in result.stdout`
- **位置**：`e2e/test_la_ops.py:177-180` · 意图由函数名推断

#### 24. `test_e2e_tasks_logs_and_delete`

- **意图**：覆盖: e2e tasks logs and delete
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`queued.returncode == 0; logs.returncode == 0; deleted.returncode == 0; '已删除' in deleted.stdout; missing.returncode == 1`
- **位置**：`e2e/test_la_ops.py:183-198` · 意图由函数名推断

#### 25. `test_e2e_cross_memory_and_rag_isolation`

- **意图**：rag add must not pollute Warm memory; memory add must still be searchable separately.
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`run_la(['rag', 'add', str(doc)], env=la_env).returncode == 0; mem.returncode == 0; 'Warm' in mem.stdout or 'memory add' in mem.stdout; rag.returncode == 0; 'UNIQUE_COLD_TOKEN_XYZ' in rag.stdout`
- **位置**：`e2e/test_la_ops.py:201-223` · 有 docstring


### `e2e/test_la_rag.py`（18）

#### 1. `test_e2e_rag_help`

- **意图**：覆盖: e2e rag help
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; token in result.stdout`
- **位置**：`e2e/test_la_rag.py:14-18` · 意图由函数名推断

#### 2. `test_e2e_rag_status_empty`

- **意图**：覆盖: e2e rag status empty
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'Cold' in result.stdout or '知识库' in result.stdout; '已索引文件' in result.stdout; '知识块数' in result.stdout; '下一步' in result.stdout`
- **位置**：`e2e/test_la_rag.py:21-27` · 意图由函数名推断

#### 3. `test_e2e_bare_rag_shows_status`

- **意图**：覆盖: e2e bare rag shows status
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '[rag status]' in result.stdout; 'kb 目录' in result.stdout; '下一步' in result.stdout`
- **位置**：`e2e/test_la_rag.py:30-35` · 意图由函数名推断

#### 4. `test_e2e_rag_add_status_search`

- **意图**：覆盖: e2e rag add status search
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`add.returncode == 0; '软链:' in add.stdout; 'done' in add.stdout; kb.is_symlink(); status.returncode == 0`
- **位置**：`e2e/test_la_rag.py:38-58` · 意图由函数名推断

#### 5. `test_e2e_rag_search_top_k`

- **意图**：覆盖: e2e rag search top k
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`run_la(['rag', 'add', str(doc)], env=la_env).returncode == 0; result.returncode == 0; result.stdout.strip()`
- **位置**：`e2e/test_la_rag.py:61-70` · 意图由函数名推断

#### 6. `test_e2e_rag_search_miss`

- **意图**：覆盖: e2e rag search miss
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`run_la(['rag', 'add', str(doc)], env=la_env).returncode == 0; result.returncode == 0; '[错误]' not in result.stdout`
- **位置**：`e2e/test_la_rag.py:73-78` · 意图由函数名推断

#### 7. `test_e2e_rag_ingest_skip_then_force`

- **意图**：覆盖: e2e rag ingest skip then force
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`run_la(['rag', 'add', str(doc)], env=la_env).returncode == 0; skipped.returncode == 0; 'skipped' in skipped.stdout or 'rag ingest' in skipped.stdout; forced.returncode == 0; 'updated' in forced.stdout or 'new' in forced.stdout or 'rag ingest' in forced.stdout`
- **位置**：`e2e/test_la_rag.py:81-91` · 意图由函数名推断

#### 8. `test_e2e_rag_ingest_new_symlink_only`

- **意图**：File already linked into kb/ without going through add should be picked up by ingest.
- **输入**：夹具: la_env, tmp_path, la_data_dir
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'new' in result.stdout or 'linked' in result.stdout or 'rag ingest' in result.stdout; search.returncode == 0; 'symlink' in search.stdout.lower() or 'ingest' in search.stdout.lower() or 'Linked' in search.stdout`
- **位置**：`e2e/test_la_rag.py:94-106` · 有 docstring

#### 9. `test_e2e_rag_reset_preserves_symlink`

- **意图**：覆盖: e2e rag reset preserves symlink
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`run_la(['rag', 'add', str(doc)], env=la_env).returncode == 0; kb.exists(); reset.returncode == 0; 'rag reset' in reset.stdout; 'done' in reset.stdout`
- **位置**：`e2e/test_la_rag.py:109-124` · 意图由函数名推断

#### 10. `test_e2e_rag_rebuild_after_reset`

- **意图**：覆盖: e2e rag rebuild after reset
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`run_la(['rag', 'add', str(doc)], env=la_env).returncode == 0; run_la(['rag', 'reset'], env=la_env).returncode == 0; rebuild.returncode == 0; 'rag rebuild' in rebuild.stdout; search.returncode == 0`
- **位置**：`e2e/test_la_rag.py:127-138` · 意图由函数名推断

#### 11. `test_e2e_rag_add_background_and_tasks`

- **意图**：覆盖: e2e rag add background and tasks
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '后台任务' in result.stdout; '软链:' in result.stdout; search.returncode == 0; 'background' in search.stdout.lower() or 'BG2' in search.stdout`
- **位置**：`e2e/test_la_rag.py:141-152` · 意图由函数名推断

#### 12. `test_e2e_rag_add_missing_file`

- **意图**：覆盖: e2e rag add missing file
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 1; 'error' in result.stdout.lower() or '不存在' in result.stdout or 'No such' in result.stdout or ('not found' in result.stdout.lower())`
- **位置**：`e2e/test_la_rag.py:155-159` · 意图由函数名推断

#### 13. `test_e2e_rag_rebuild_empty_kb`

- **意图**：覆盖: e2e rag rebuild empty kb
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; 'rag rebuild' in result.stdout`
- **位置**：`e2e/test_la_rag.py:162-165` · 意图由函数名推断

#### 14. `test_e2e_rag_rebuild_idempotent`

- **意图**：覆盖: e2e rag rebuild idempotent
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`run_la(['rag', 'add', str(doc)], env=la_env).returncode == 0; first.returncode == 0; second.returncode == 0; 'rag rebuild' in first.stdout`
- **位置**：`e2e/test_la_rag.py:168-175` · 意图由函数名推断

#### 15. `test_e2e_rag_reset_keep_index_flag`

- **意图**：覆盖: e2e rag reset keep index flag
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`run_la(['rag', 'add', str(doc)], env=la_env).returncode == 0; help_.returncode == 0; result.returncode == 0; 'rag reset' in result.stdout`
- **位置**：`e2e/test_la_rag.py:178-185` · 意图由函数名推断

#### 16. `test_e2e_rag_status_after_add_lists_file`

- **意图**：覆盖: e2e rag status after add lists file
- **输入**：夹具: la_env, tmp_path
- **方法**：CLI/subprocess + temp data
- **校验**：`run_la(['rag', 'add', str(doc)], env=la_env).returncode == 0; status.returncode == 0; '已索引文件' in status.stdout; '知识块数' in status.stdout; '下一步' in status.stdout`
- **位置**：`e2e/test_la_rag.py:188-196` · 意图由函数名推断

#### 17. `test_e2e_rag_ingest_help`

- **意图**：覆盖: e2e rag ingest help
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '--force' in result.stdout`
- **位置**：`e2e/test_la_rag.py:199-202` · 意图由函数名推断

#### 18. `test_e2e_rag_search_help`

- **意图**：覆盖: e2e rag search help
- **输入**：夹具: la_env
- **方法**：CLI/subprocess + temp data
- **校验**：`result.returncode == 0; '--top-k' in result.stdout or 'query' in result.stdout.lower()`
- **位置**：`e2e/test_la_rag.py:205-208` · 意图由函数名推断


## Benchmark

### `test_locomo_benchmark.py`（9）

#### 1. `test_category_names_cover_official_ids`

- **意图**：覆盖: category names cover official ids
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`set(CATEGORY_NAMES) == {1, 2, 3, 4, 5}`
- **位置**：`test_locomo_benchmark.py:25-26` · 意图由函数名推断

#### 2. `test_f1_and_multi_answer_scoring`

- **意图**：覆盖: f1 and multi answer scoring
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`f1_score('Sunny', 'Sunny') == 1.0; f1_score('a golden dog', 'golden retriever') > 0; multi_answer_f1('pottery, Clara', 'pottery, Clara') == 1.0`
- **位置**：`test_locomo_benchmark.py:29-32` · 意图由函数名推断

#### 3. `test_adversarial_scoring_accepts_abstain`

- **意图**：覆盖: adversarial scoring accepts abstain
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`score_qa_item(category=5, prediction='No information available', answer=None) == 1.0; score_qa_item(category=5, prediction='red', answer=None) == 0.0`
- **位置**：`test_locomo_benchmark.py:35-37` · 意图由函数名推断

#### 4. `test_open_domain_uses_first_semicolon_segment`

- **意图**：覆盖: open domain uses first semicolon segment
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`score == 1.0`
- **位置**：`test_locomo_benchmark.py:40-46` · 意图由函数名推断

#### 5. `test_summarize_scores_by_category`

- **意图**：覆盖: summarize scores by category
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`summary['n'] == 3; summary['overall_f1'] == 0.6667; summary['categories']['4']['n'] == 2; summary['categories']['4']['f1'] == 0.5`
- **位置**：`test_locomo_benchmark.py:49-60` · 意图由函数名推断

#### 6. `test_load_fixture_and_format_turns`

- **意图**：覆盖: load fixture and format turns
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`len(samples) == 1; any((i['metadata']['kind'] == 'conversation_meta' for i in items)); len(dialogs) == 4; 'Sunny' in dialogs[0]['text']; 'dia_id=D1:1' in dialogs[0]['text']`
- **位置**：`test_locomo_benchmark.py:63-79` · 意图由函数名推断

#### 7. `test_filter_samples`

- **意图**：覆盖: filter samples
- **输入**：无外部夹具
- **方法**：unit
- **校验**：`filter_samples(samples, sample_ids=['missing']) == []; filter_samples(samples, sample_ids=['conv-tiny'])[0]['sample_id'] == 'conv-tiny'`
- **位置**：`test_locomo_benchmark.py:82-85` · 意图由函数名推断

#### 8. `test_ingest_tiny_into_isolated_json_backend`

- **意图**：覆盖: ingest tiny into isolated json backend
- **输入**：夹具: tmp_path
- **方法**：mock + temp data
- **校验**：`info['written'] >= 4; info['memory_count'] >= 4; any(('Sunny' in (h.get('text') or '') for h in hits))`
- **位置**：`test_locomo_benchmark.py:88-101` · 意图由函数名推断

#### 9. `test_end_to_end_recall_mode_scores`

- **意图**：覆盖: end to end recall mode scores
- **输入**：夹具: tmp_path
- **方法**：mock + temp data
- **校验**：`'Sunny' in result['prediction']; f1 > 0.0`
- **位置**：`test_locomo_benchmark.py:104-128` · 意图由函数名推断

