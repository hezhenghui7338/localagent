(() => {
  // v3: English-first. Ignore legacy auto-detect / sticky zh caches.
  const STORAGE_KEY = "la-site-lang-v3";
  const LEGACY_STORAGE_KEYS = ["la-site-lang", "la-site-lang-v2"];
  const INSTALL_CMD =
    'pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.6.0"\nla';

  const DEMO_IDS = ["setup", "memory", "deepread", "aware"];
  /** Demos without MP4 assets — always use steps mode. */
  const STEPS_ONLY_DEMOS = ["aware"];
  const DEMO_PLAYBACK_RATE = 1.25;

  const strings = {
    zh: {
      "nav.features": "特性",
      "nav.demo": "演示",
      "nav.install": "安装",
      "nav.contact": "联系",
      "hero.tagline": "Local First. Memory Forever. Actions Automated.",
      "hero.lead": "本地 AI：记得住你，也能把事办完。",
      "hero.ctaGithub": "在 GitHub 查看",
      "hero.ctaInstall": "快速安装",
      "hero.ctaDemo": "看演示 →",
      "features.eyebrow": "产品设计",
      "features.title": "本地优先。真记得你。把事办完。",
      "features.lead":
        "装上就能聊、能记住、能动手办事——默认本机跑通，云端可选。身份、记忆与审计档案存本机、不上传；选用云端模型或联网搜索时，当轮内容会发往对应服务。",
      "features.f1.title": "Local First",
      "features.f1.body":
        "默认零账单路径：对话、记忆、检索、工具可纯本地跑通。主路径 <code>la</code> · <code>la setup</code> · <code>la chat</code>。可选云端——档案留本机；当轮 prompt 可能外发。",
      "features.f1.link": "看「零成本上手」演示 →",
      "features.f2.title": "Memory Forever",
      "features.f2.body":
        "Hot / Warm / Cold + Mem0 跨会话持久。记住你，也懂得该记什么、别记什么、何时介入。文档进本地知识库，深度召回原文。",
      "features.f2.link": "看「真记住你」演示 →",
      "features.f3.title": "Actions Automated",
      "features.f3.body":
        "Shell、写文件、工作区；summarize · news · polish · <strong>aware</strong>（需授权、不自动入库）；定时简报。执行前确认，危险硬拦，办完有回执。",
      "features.f3.link": "看「本机感知」演示 →",
      "demo.eyebrow": "演示",
      "demo.title": "几件事，马上感受到",
      "demo.lead":
        "可分步查看，也可看短片（Aware 目前仅分步）——不接云端推理。装上本机后，这些就是真实路径。",
      "demo.tab.setup": "上手",
      "demo.tab.memory": "记住你",
      "demo.tab.deepread": "深聊",
      "demo.tab.aware": "感知",
      "demo.mode.steps": "分步",
      "demo.mode.video": "视频",
      "demo.prev": "上一步",
      "demo.next": "下一步",
      "demo.replay": "重播",
      "demo.progress": "{current} / {total}",
      "demo.moreTour": "完整产品漫游 →",
      "demo.moreInstall": "去安装 →",
      "demo.setup.title": "本机一键，默认可零成本",
      "demo.setup.body":
        "不绑账号也能聊；默认算力在本机，记忆与审计档案不上传。",
      "demo.setup.note":
        "默认 Ollama 本地路径；账单可为 $0。",
      "demo.memory.title": "关掉窗口，它还记得你",
      "demo.memory.body":
        "新会话照样叫得出名字、偏好和关键决策——记忆在本机，不在聊天记录里。",
      "demo.memory.note":
        "对比：典型聊天客户端换会话就忘；LocalAgent 从 Warm / Hot 召回。",
      "demo.deepread.title": "一篇文章，聊到懂",
      "demo.deepread.body":
        "先速读，再围着原文追问；今日资讯精读也是同一套深聊。",
      "demo.deepread.note":
        "summarize 与 news 精读共用 DocumentChat。本机上下文见「感知」演示。",
      "demo.aware.title": "本机感知，先授权再采集",
      "demo.aware.body":
        "按源 grant 后 tick 一轮：文件、终端、浏览器与前台应用变成 Episode。可索引文件只进 suggestion，绝不自动写 Cold。",
      "demo.aware.note":
        "默认关闭；浏览器选中 ≠ 正在看；不录屏、不记按键内容。",
      "install.eyebrow": "快速开始",
      "install.title": "一行命令，装上就聊",
      "install.lead": "需要 Python 3.10+ 与 pipx。当前版本 v0.6.0。",
      "install.copy": "复制",
      "install.copied": "已复制",
      "install.hint":
        "有 API → 写入 Key；无 API → <code>la setup -y</code> 装 Ollama。",
      "install.trust1": "默认本机 Ollama——零账单、无需账号。",
      "install.trust2": "副作用（Shell / 写文件）执行前会确认。",
      "install.trust3":
        "云端模型或联网搜索会外发当轮内容；可用 <code>/provider ollama</code> 切回本地。",
      "install.docs": "完整文档与升级说明 →",
      "contact.eyebrow": "联系",
      "contact.title": "打招呼",
      "contact.lead":
        "不是又一个 Chat 客户端——本地 AI：记得住你，也能把事办完。问题、建议或合作，欢迎来信。",
      "contact.emailLabel": "邮箱",
      "footer.line": "LocalAgent · MIT · v0.6.0",
      title: "LocalAgent — 本地 AI：记得住你，也能把事办完",
      description:
        "LocalAgent — Local First. Memory Forever. Actions Automated. 本地 AI：记得住你，也能把事办完。",
    },
    en: {
      "nav.features": "Features",
      "nav.demo": "Demo",
      "nav.install": "Install",
      "nav.contact": "Contact",
      "hero.tagline": "Local First. Memory Forever. Actions Automated.",
      "hero.lead": "Local AI that remembers and gets things done.",
      "hero.ctaGithub": "View on GitHub",
      "hero.ctaInstall": "Quick install",
      "hero.ctaDemo": "See the demo →",
      "features.eyebrow": "Product design",
      "features.title":
        "Local first. Really remembers you. Gets things done.",
      "features.lead":
        "Install and you’re chatting, remembered, and getting work done — on-device by default, cloud optional. Identity, memory, and audit archives stay on-device; cloud chat or web search sends that turn’s content to the provider.",
      "features.f1.title": "Local First",
      "features.f1.body":
        "Zero-bill default path: chat, memory, retrieval, and tools run on-device. Main path: <code>la</code> · <code>la setup</code> · <code>la chat</code>. Optional cloud — archives stay local; that turn’s prompt may leave.",
      "features.f1.link": "See the zero-cost setup demo →",
      "features.f2.title": "Memory Forever",
      "features.f2.body":
        "Hot / Warm / Cold + Mem0 across sessions. Remembers you — and knows what to keep, what to drop, and when to step in. Docs go into a local KB for deep recall.",
      "features.f2.link": "See the “remembers you” demo →",
      "features.f3.title": "Actions Automated",
      "features.f3.body":
        "Shell, file writes, workspace; summarize · news · polish · <strong>aware</strong> (opt-in; never auto-archives); scheduled brief. Confirm before side effects, block danger, show a receipt when done.",
      "features.f3.link": "See the Aware demo →",
      "demo.eyebrow": "Demo",
      "demo.title": "Moments you can feel",
      "demo.lead":
        "Step through the walkthrough, or watch a short clip (Aware is steps-only for now) — no hosted model. On your machine, these are the real paths.",
      "demo.tab.setup": "Setup",
      "demo.tab.memory": "Memory",
      "demo.tab.deepread": "Deep read",
      "demo.tab.aware": "Aware",
      "demo.mode.steps": "Steps",
      "demo.mode.video": "Video",
      "demo.prev": "Back",
      "demo.next": "Next",
      "demo.replay": "Replay",
      "demo.progress": "{current} / {total}",
      "demo.moreTour": "Full product tour →",
      "demo.moreInstall": "Install →",
      "demo.setup.title": "One step local. Zero bill by default.",
      "demo.setup.body":
        "No account required to chat. Default compute is on-device; memory and audit archives are not uploaded.",
      "demo.setup.note":
        "Default path is Ollama on-device — cost can be $0.",
      "demo.memory.title": "Close the window. It still knows you.",
      "demo.memory.body":
        "A new session still recalls your name, preferences, and key decisions — memory lives on-device, not in the chat transcript.",
      "demo.memory.note":
        "Contrast: a typical chat client forgets across sessions. LocalAgent recalls from Warm / Hot.",
      "demo.deepread.title": "One article. Talk until you get it.",
      "demo.deepread.body":
        "Skim first, then ask against the source. News deep-read uses the same document chat.",
      "demo.deepread.note":
        "summarize and news deep-read share DocumentChat. For on-device context, see the Aware demo.",
      "demo.aware.title": "Sense your machine — grant first",
      "demo.aware.body":
        "After per-source grant, one tick turns files, terminal, browser, and focus apps into episodes. Indexable files become suggestions only — never auto-written to Cold.",
      "demo.aware.note":
        "Off by default. Browser selected ≠ viewing. No screen capture, no keystroke content.",
      "install.eyebrow": "Quick start",
      "install.title": "One command, then chat",
      "install.lead": "Needs Python 3.10+ and pipx. Current version v0.6.0.",
      "install.copy": "Copy",
      "install.copied": "Copied",
      "install.hint":
        "Have an API → set your key. No API → <code>la setup -y</code> for Ollama.",
      "install.trust1": "Default path is local Ollama — zero bill, no account.",
      "install.trust2": "Side effects (shell / write file) ask before running.",
      "install.trust3":
        "Cloud models or web search send that turn’s content outbound; switch back with <code>/provider ollama</code>.",
      "install.docs": "Full docs & upgrade notes →",
      "contact.eyebrow": "Contact",
      "contact.title": "Say hello",
      "contact.lead":
        "Not another chat client — local AI that remembers and gets things done. Questions, ideas, or collaboration welcome.",
      "contact.emailLabel": "Email",
      "footer.line": "LocalAgent · MIT · v0.6.0",
      title: "LocalAgent — Local AI that remembers and gets things done",
      description:
        "LocalAgent — Local First. Memory Forever. Actions Automated. Local AI that remembers and gets things done.",
    },
  };

  /** @type {Record<string, Record<string, { lines: { kind: string, text: string }[] }[]>>} */
  const demoScripts = {
    zh: {
      setup: [
        {
          lines: [
            { kind: "prompt", text: "$ pipx install \"git+https://github.com/hezhenghui7338/localagent.git@v0.6.0\"" },
            { kind: "prompt", text: "$ la --version" },
            { kind: "out", text: "la-localagent 0.6.0" },
          ],
        },
        {
          lines: [
            { kind: "prompt", text: "$ la setup -y" },
            { kind: "out", text: "[setup] Ollama detected" },
            { kind: "out", text: "[setup] model ready: qwen3.5:4b" },
            { kind: "dim", text: "无需账号 · 默认本机算力" },
          ],
        },
        {
          lines: [
            { kind: "prompt", text: "$ la chat --provider ollama" },
            { kind: "you", text: "you> 用一句话介绍自己，并说明数据存在哪。" },
            { kind: "meta", text: "[chat] generating…" },
            {
              kind: "assistant",
              text: "我是运行在你机器上的 LocalAgent：对话、记忆与审计都留在本机数据目录——身份数据不会上传到云端。",
            },
            { kind: "dim", text: "[via ollama/qwen3.5:4b]" },
          ],
        },
        {
          lines: [
            { kind: "prompt", text: "$ la audit" },
            { kind: "out", text: "## Tokens & service cost" },
            { kind: "out", text: "provider: ollama" },
            { kind: "accent", text: "estimated cost: $0.00" },
            { kind: "dim", text: "装上就能聊 · 默认可零账单" },
          ],
        },
      ],
      memory: [
        {
          lines: [
            { kind: "label", text: "Session A" },
            { kind: "prompt", text: "$ la chat --session-id tour-a" },
            {
              kind: "you",
              text: "you> Remember: next week I’ll demo LocalAgent’s memory layers to the team.",
            },
            {
              kind: "assistant",
              text: "assistant> Got it — noted that you’ll demo the memory layers next week.",
            },
          ],
        },
        {
          lines: [
            { kind: "you", text: "you> /q" },
            { kind: "dim", text: "会话结束。记忆写入本机 Warm / Hot。" },
          ],
        },
        {
          lines: [
            { kind: "label", text: "Session B — 全新会话" },
            { kind: "prompt", text: "$ la chat --session-id tour-b" },
            {
              kind: "you",
              text: "you> What’s my name? What do I like to drink? What meeting did I have in Shenzhen in May?",
            },
            { kind: "meta", text: "[chat] calling search_memory…" },
          ],
        },
        {
          lines: [
            {
              kind: "assistant",
              text: "You’re Alex Lin; you prefer Americano (dislike latte).",
            },
            {
              kind: "assistant",
              text: "In May 2026 you held a Shenzhen product roadmap meeting and decided to prioritize a personal AI assistant on your machine.",
            },
            { kind: "dim", text: "[via ollama/qwen3.5:4b]" },
            {
              kind: "accent",
              text: "不是当前 transcript —— 从本机 Warm / Hot 召回。",
            },
          ],
        },
      ],
      deepread: [
        {
          lines: [
            { kind: "label", text: "文档速读" },
            { kind: "prompt", text: "$ la summarize examples/sample-project-notes.md" },
            { kind: "out", text: "## 总结（最多三句话）" },
            {
              kind: "out",
              text: "LocalAgent 采用 Hot / Warm / Cold 三层记忆；换模型不换身份。本机可用 Ollama + qwen3.5:4b 跑通对话与检索。",
            },
            { kind: "out", text: "## 结构化要点" },
            {
              kind: "out",
              text: "- **架构**：Hot / Warm / Cold — 依据：原文 〔§架构决策〕",
            },
            {
              kind: "out",
              text: "- **本地**：Ollama + qwen3.5:4b — 依据：原文 〔§本地运行〕",
            },
          ],
        },
        {
          lines: [
            { kind: "dim", text: "进入文档对话（默认不入库；/keep 才归档）" },
            {
              kind: "you",
              text: "sum> 检索方案和语义权重是怎么定的？",
            },
            {
              kind: "assistant",
              text: "默认语义权重 LA_SEMANTIC_WEIGHT=0.75，BM25 补关键词；长文档导入时索引与记忆提取分离。 〔§检索方案〕",
            },
          ],
        },
        {
          lines: [
            { kind: "label", text: "资讯简报" },
            { kind: "prompt", text: "$ la news sync && la news brief" },
            { kind: "out", text: "↑↓ 选择 · o 打开 · r 精读" },
            {
              kind: "accent",
              text: "▸ Open-source personal AI agents in 2026",
            },
            { kind: "out", text: "  Local-first memory stacks, no cloud lock-in" },
            { kind: "dim", text: "  BestBlogs · 2h ago · interest ★★★★" },
          ],
        },
        {
          lines: [
            { kind: "you", text: "(press r) → 抓正文，进入同一套深聊" },
            {
              kind: "you",
              text: "sum> 这篇文章对「本机记忆」的核心主张是什么？",
            },
            {
              kind: "assistant",
              text: "主张身份与长期记忆留在本机：模型可替换，记忆层不可被会话清空。 〔§导语 | p.1〕",
            },
            {
              kind: "accent",
              text: "news 精读 = summarize 同款 DocumentChat",
            },
          ],
        },
      ],
      aware: [
        {
          lines: [
            { kind: "prompt", text: "$ la aware status" },
            { kind: "out", text: "Aware: off (no sources granted)" },
            { kind: "dim", text: "默认关闭 · 按源 opt-in" },
          ],
        },
        {
          lines: [
            { kind: "prompt", text: "$ la aware grant fs terminal browser apps -y" },
            { kind: "out", text: "Granted: fs · terminal · browser · apps" },
            { kind: "dim", text: "敏感源也可去掉 -y 交互确认" },
          ],
        },
        {
          lines: [
            { kind: "prompt", text: "$ la aware tick --no-chat" },
            { kind: "out", text: "[tick] fs: 3 events · browser: 1 viewing · apps: Cursor" },
            { kind: "out", text: "[tick] episodes updated · 1 suggestion pending" },
          ],
        },
        {
          lines: [
            { kind: "prompt", text: "$ la aware suggestion" },
            {
              kind: "accent",
              text: "s1  ingest doc ~/Notes/roadmap.md  (approve 后才入库)",
            },
            { kind: "dim", text: "绝不自动写 Cold / kb/ · approve 仅白名单" },
          ],
        },
        {
          lines: [
            { kind: "prompt", text: "$ la aware --no-chat" },
            { kind: "out", text: "## Now" },
            { kind: "out", text: "前台 Cursor · 正在看 docs · 近 3h 改了 README" },
            { kind: "accent", text: "相关 la chat 可注入 Episode · selected ≠ viewing" },
          ],
        },
      ],
    },
    en: {
      setup: [
        {
          lines: [
            { kind: "prompt", text: "$ pipx install \"git+https://github.com/hezhenghui7338/localagent.git@v0.6.0\"" },
            { kind: "prompt", text: "$ la --version" },
            { kind: "out", text: "la-localagent 0.6.0" },
          ],
        },
        {
          lines: [
            { kind: "prompt", text: "$ la setup -y" },
            { kind: "out", text: "[setup] Ollama detected" },
            { kind: "out", text: "[setup] model ready: qwen3.5:4b" },
            { kind: "dim", text: "No account · on-device compute by default" },
          ],
        },
        {
          lines: [
            { kind: "prompt", text: "$ la chat --provider ollama" },
            {
              kind: "you",
              text: "you> In one sentence, introduce yourself and say where your data lives.",
            },
            { kind: "meta", text: "[chat] generating…" },
            {
              kind: "assistant",
              text: "I’m LocalAgent running on your machine: chat, memory, and audit archives stay in the local data directory — not uploaded by LocalAgent.",
            },
            { kind: "dim", text: "[via ollama/qwen3.5:4b]" },
          ],
        },
        {
          lines: [
            { kind: "prompt", text: "$ la audit" },
            { kind: "out", text: "## Tokens & service cost" },
            { kind: "out", text: "provider: ollama" },
            { kind: "accent", text: "estimated cost: $0.00" },
            { kind: "dim", text: "Ready to chat · zero bill by default" },
          ],
        },
      ],
      memory: [
        {
          lines: [
            { kind: "label", text: "Session A" },
            { kind: "prompt", text: "$ la chat --session-id tour-a" },
            {
              kind: "you",
              text: "you> Remember: next week I’ll demo LocalAgent’s memory layers to the team.",
            },
            {
              kind: "assistant",
              text: "assistant> Got it — noted that you’ll demo the memory layers next week.",
            },
          ],
        },
        {
          lines: [
            { kind: "you", text: "you> /q" },
            { kind: "dim", text: "Session ended. Memory kept in on-device Warm / Hot." },
          ],
        },
        {
          lines: [
            { kind: "label", text: "Session B — brand-new session" },
            { kind: "prompt", text: "$ la chat --session-id tour-b" },
            {
              kind: "you",
              text: "you> What’s my name? What do I like to drink? What meeting did I have in Shenzhen in May?",
            },
            { kind: "meta", text: "[chat] calling search_memory…" },
          ],
        },
        {
          lines: [
            {
              kind: "assistant",
              text: "You’re Alex Lin; you prefer Americano (dislike latte).",
            },
            {
              kind: "assistant",
              text: "In May 2026 you held a Shenzhen product roadmap meeting and decided to prioritize a personal AI assistant on your machine.",
            },
            { kind: "dim", text: "[via ollama/qwen3.5:4b]" },
            {
              kind: "accent",
              text: "Not the current transcript — recalled from on-device Warm / Hot.",
            },
          ],
        },
      ],
      deepread: [
        {
          lines: [
            { kind: "label", text: "Document skim" },
            { kind: "prompt", text: "$ la summarize examples/sample-project-notes.md" },
            { kind: "out", text: "## Summary (≤3 sentences)" },
            {
              kind: "out",
              text: "LocalAgent uses Hot / Warm / Cold memory; swap the model, keep the identity. On-device Ollama + qwen3.5:4b runs chat and retrieval.",
            },
            { kind: "out", text: "## Key points" },
            {
              kind: "out",
              text: "- **Architecture**: Hot / Warm / Cold — source 〔§Architecture〕",
            },
            {
              kind: "out",
              text: "- **Local**: Ollama + qwen3.5:4b — source 〔§Local run〕",
            },
          ],
        },
        {
          lines: [
            {
              kind: "dim",
              text: "Document chat (not kept by default; /keep to archive)",
            },
            {
              kind: "you",
              text: "sum> How is retrieval weighted?",
            },
            {
              kind: "assistant",
              text: "Default semantic weight LA_SEMANTIC_WEIGHT=0.75, with BM25 for keywords; indexing and memory extract stay separate on long docs. 〔§Retrieval〕",
            },
          ],
        },
        {
          lines: [
            { kind: "label", text: "News brief" },
            { kind: "prompt", text: "$ la news sync && la news brief" },
            { kind: "out", text: "↑↓ select · o open · r deep-read" },
            {
              kind: "accent",
              text: "▸ Open-source personal AI agents in 2026",
            },
            { kind: "out", text: "  Local-first memory stacks, no cloud lock-in" },
            { kind: "dim", text: "  BestBlogs · 2h ago · interest ★★★★" },
          ],
        },
        {
          lines: [
            { kind: "you", text: "(press r) → fetch body, same deep-read chat" },
            {
              kind: "you",
              text: "sum> What’s the core claim about on-device memory?",
            },
            {
              kind: "assistant",
              text: "Identity and long-term memory stay on-device: models are swappable; memory must not vanish with a session. 〔§Lead | p.1〕",
            },
            {
              kind: "accent",
              text: "News deep-read = the same DocumentChat as summarize",
            },
          ],
        },
      ],
      aware: [
        {
          lines: [
            { kind: "prompt", text: "$ la aware status" },
            { kind: "out", text: "Aware: off (no sources granted)" },
            { kind: "dim", text: "Off by default · per-source opt-in" },
          ],
        },
        {
          lines: [
            { kind: "prompt", text: "$ la aware grant fs terminal browser apps -y" },
            { kind: "out", text: "Granted: fs · terminal · browser · apps" },
            { kind: "dim", text: "Omit -y to confirm sensitive sources interactively" },
          ],
        },
        {
          lines: [
            { kind: "prompt", text: "$ la aware tick --no-chat" },
            { kind: "out", text: "[tick] fs: 3 events · browser: 1 viewing · apps: Cursor" },
            { kind: "out", text: "[tick] episodes updated · 1 suggestion pending" },
          ],
        },
        {
          lines: [
            { kind: "prompt", text: "$ la aware suggestion" },
            {
              kind: "accent",
              text: "s1  ingest doc ~/Notes/roadmap.md  (archive only after approve)",
            },
            { kind: "dim", text: "Never auto-writes Cold / kb/ · whitelist approve only" },
          ],
        },
        {
          lines: [
            { kind: "prompt", text: "$ la aware --no-chat" },
            { kind: "out", text: "## Now" },
            { kind: "out", text: "Focus: Cursor · viewing docs · edited README in last 3h" },
            { kind: "accent", text: "Relevant la chat can inject episodes · selected ≠ viewing" },
          ],
        },
      ],
    },
  };

  let currentLang = "en";
  let activeDemo = "setup";
  let stepIndex = 0;
  let demoMode = "steps";

  function preferredLang() {
    try {
      for (const key of LEGACY_STORAGE_KEYS) {
        localStorage.removeItem(key);
      }
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved === "zh" || saved === "en") return saved;
    } catch {
      /* private mode / blocked storage */
    }
    return "en";
  }

  function prefersReducedMotion() {
    return (
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  function demoAssetBase(lang, id) {
    const safeLang = lang === "zh" ? "zh" : "en";
    const safeId = DEMO_IDS.includes(id) ? id : "setup";
    return `assets/demos/${safeId}.${safeLang}`;
  }

  function applyLang(lang, { persist = false } = {}) {
    const next = lang === "zh" ? "zh" : "en";
    currentLang = next;
    const dict = strings[next];

    document.documentElement.lang = next === "zh" ? "zh-CN" : "en";
    document.title = dict.title;

    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.setAttribute("content", dict.description);

    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      const value = dict[key];
      if (value == null) return;
      el.innerHTML = value;
    });

    const logo = document.getElementById("hero-logo");
    if (logo) {
      logo.src =
        next === "zh" ? "assets/logo.zh-CN.png" : "assets/logo.png";
    }

    document.querySelectorAll(".lang-switch [data-lang]").forEach((btn) => {
      btn.classList.toggle(
        "is-active",
        btn.getAttribute("data-lang") === next,
      );
    });

    if (persist) {
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        /* ignore */
      }
    }

    renderDemo();
  }

  function setupLangSwitch() {
    document.querySelectorAll(".lang-switch [data-lang]").forEach((btn) => {
      btn.addEventListener("click", () => {
        applyLang(btn.getAttribute("data-lang"), { persist: true });
      });
    });
  }

  function setupCopy() {
    const btn = document.getElementById("copy-install");
    if (!btn) return;

    btn.addEventListener("click", async () => {
      const dict = strings[currentLang] || strings.en;
      try {
        await navigator.clipboard.writeText(INSTALL_CMD);
      } catch {
        const ta = document.createElement("textarea");
        ta.value = INSTALL_CMD;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      btn.textContent = dict["install.copied"];
      btn.classList.add("is-copied");
      window.setTimeout(() => {
        btn.textContent = dict["install.copy"];
        btn.classList.remove("is-copied");
      }, 1600);
    });
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function demoSteps() {
    const pack = demoScripts[currentLang] || demoScripts.en;
    return pack[activeDemo] || pack.setup;
  }

  function renderDemoAside() {
    const dict = strings[currentLang] || strings.en;
    const title = document.getElementById("demo-aside-title");
    const body = document.getElementById("demo-aside-body");
    const note = document.getElementById("demo-aside-note");
    if (title) title.textContent = dict[`demo.${activeDemo}.title`];
    if (body) body.textContent = dict[`demo.${activeDemo}.body`];
    if (note) note.textContent = dict[`demo.${activeDemo}.note`];
  }

  function renderDemoLines() {
    const body = document.getElementById("demo-lines");
    if (!body) return;

    const steps = demoSteps();
    const max = Math.min(stepIndex, steps.length - 1);
    const fragment = document.createDocumentFragment();

    for (let i = 0; i <= max; i += 1) {
      const step = steps[i];
      step.lines.forEach((line) => {
        const el = document.createElement("div");
        el.className = `demo-line demo-line--${line.kind}`;
        el.innerHTML = escapeHtml(line.text);
        fragment.appendChild(el);
      });
      if (i < max) {
        const gap = document.createElement("div");
        gap.className = "demo-line-gap";
        gap.setAttribute("aria-hidden", "true");
        fragment.appendChild(gap);
      }
    }

    body.replaceChildren(fragment);
    body.scrollTop = body.scrollHeight;
  }

  function renderDemoControls() {
    const dict = strings[currentLang] || strings.en;
    const steps = demoSteps();
    const total = steps.length;
    const current = Math.min(stepIndex + 1, total);

    const progress = document.getElementById("demo-progress");
    if (progress) {
      progress.textContent = dict["demo.progress"]
        .replace("{current}", String(current))
        .replace("{total}", String(total));
    }

    const prev = document.getElementById("demo-prev");
    const next = document.getElementById("demo-next");
    if (prev) prev.disabled = stepIndex <= 0;
    if (next) next.disabled = stepIndex >= total - 1;
  }

  function renderDemoTabs() {
    document.querySelectorAll("[data-demo-tab]").forEach((btn) => {
      const id = btn.getAttribute("data-demo-tab");
      const selected = id === activeDemo;
      btn.classList.toggle("is-active", selected);
      btn.setAttribute("aria-selected", selected ? "true" : "false");
      btn.setAttribute("tabindex", selected ? "0" : "-1");
    });

    const panel = document.getElementById("demo-panel");
    if (panel) {
      panel.setAttribute("aria-labelledby", `demo-tab-${activeDemo}`);
    }
  }

  function renderDemoMode() {
    const stepsOnly = STEPS_ONLY_DEMOS.includes(activeDemo);
    document.querySelectorAll("[data-demo-mode]").forEach((btn) => {
      const mode = btn.getAttribute("data-demo-mode");
      btn.classList.toggle("is-active", mode === demoMode);
      if (mode === "video") {
        btn.hidden = stepsOnly;
        btn.setAttribute("aria-hidden", stepsOnly ? "true" : "false");
      }
    });

    const stepsPanel = document.getElementById("demo-steps-panel");
    const videoPanel = document.getElementById("demo-video-panel");
    if (stepsPanel) stepsPanel.classList.toggle("is-hidden", demoMode !== "steps");
    if (videoPanel) videoPanel.classList.toggle("is-hidden", demoMode !== "video");
  }

  function pauseDemoVideo() {
    const video = document.getElementById("demo-video");
    if (!video) return;
    video.pause();
    video.removeAttribute("autoplay");
  }

  function syncDemoVideo() {
    const video = document.getElementById("demo-video");
    const source = document.getElementById("demo-video-src");
    if (!video || !source) return;

    const base = demoAssetBase(currentLang, activeDemo);
    const nextPoster = `${base}.poster.jpg`;
    video.setAttribute("poster", nextPoster);

    if (demoMode !== "video") {
      pauseDemoVideo();
      return;
    }

    const nextSrc = `${base}.mp4`;
    const currentSrc = source.getAttribute("src") || "";
    if (currentSrc !== nextSrc) {
      source.setAttribute("src", nextSrc);
      video.load();
    }

    video.playbackRate = DEMO_PLAYBACK_RATE;

    if (prefersReducedMotion()) {
      pauseDemoVideo();
      return;
    }

    video.setAttribute("autoplay", "");
    const play = video.play();
    if (play && typeof play.catch === "function") {
      play.catch(() => {
        /* autoplay may be blocked; poster remains visible */
      });
    }
  }

  function renderDemo() {
    renderDemoTabs();
    renderDemoAside();
    renderDemoMode();
    if (demoMode === "steps") {
      renderDemoLines();
      renderDemoControls();
      pauseDemoVideo();
    } else {
      syncDemoVideo();
    }
  }

  function setDemoMode(mode) {
    let next = mode === "video" ? "video" : "steps";
    if (next === "video" && STEPS_ONLY_DEMOS.includes(activeDemo)) {
      next = "steps";
    }
    if (demoMode === next) return;
    demoMode = next;
    renderDemo();
  }

  function scrollDemoIntoView() {
    const root = document.getElementById("demo");
    if (!root) return;
    root.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function setDemo(id, { resetStep = true, updateHash = true, scroll = false } = {}) {
    if (!DEMO_IDS.includes(id)) return;
    activeDemo = id;
    if (STEPS_ONLY_DEMOS.includes(id) && demoMode === "video") {
      demoMode = "steps";
    }
    if (resetStep) stepIndex = 0;
    renderDemo();
    if (updateHash) {
      const hash = `#demo-${id}`;
      if (location.hash !== hash) {
        history.replaceState(null, "", hash);
      }
    }
    if (scroll) scrollDemoIntoView();
  }

  function parseDemoHash() {
    const hash = (location.hash || "").replace(/^#/, "");
    if (hash === "demo") return "setup";
    if (hash.startsWith("demo-")) {
      const id = hash.slice("demo-".length);
      if (DEMO_IDS.includes(id)) return id;
    }
    return null;
  }

  function setupDemo() {
    const root = document.getElementById("demo");
    if (!root) return;

    document.querySelectorAll("[data-demo-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        setDemo(btn.getAttribute("data-demo-tab"));
      });
    });

    document.querySelectorAll("[data-demo-jump]").forEach((link) => {
      link.addEventListener("click", (event) => {
        const id = link.getAttribute("data-demo-jump");
        if (!DEMO_IDS.includes(id)) return;
        event.preventDefault();
        setDemo(id, { scroll: true });
      });
    });

    document.querySelectorAll("[data-demo-mode]").forEach((btn) => {
      btn.addEventListener("click", () => {
        setDemoMode(btn.getAttribute("data-demo-mode"));
      });
    });

    const prev = document.getElementById("demo-prev");
    const next = document.getElementById("demo-next");
    const replay = document.getElementById("demo-replay");

    if (prev) {
      prev.addEventListener("click", () => {
        if (stepIndex > 0) {
          stepIndex -= 1;
          renderDemo();
        }
      });
    }
    if (next) {
      next.addEventListener("click", () => {
        const steps = demoSteps();
        if (stepIndex < steps.length - 1) {
          stepIndex += 1;
          renderDemo();
        }
      });
    }
    if (replay) {
      replay.addEventListener("click", () => {
        stepIndex = 0;
        renderDemo();
      });
    }

    if (typeof window.matchMedia === "function") {
      const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
      const onChange = () => {
        if (demoMode === "video") syncDemoVideo();
      };
      if (typeof mq.addEventListener === "function") {
        mq.addEventListener("change", onChange);
      } else if (typeof mq.addListener === "function") {
        mq.addListener(onChange);
      }
    }

    window.addEventListener("hashchange", () => {
      const id = parseDemoHash();
      if (id) setDemo(id, { updateHash: false, scroll: true });
    });

    const fromHash = parseDemoHash();
    if (fromHash) {
      activeDemo = fromHash;
      stepIndex = 0;
    }
    renderDemo();

    if (fromHash && (location.hash || "").startsWith("#demo-")) {
      window.requestAnimationFrame(scrollDemoIntoView);
    }
  }

  applyLang(preferredLang());
  setupLangSwitch();
  setupCopy();
  setupDemo();
})();
