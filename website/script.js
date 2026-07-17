(() => {
  const STORAGE_KEY = "la-site-lang";
  const INSTALL_CMD =
    'pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"\nla';

  const strings = {
    zh: {
      "nav.features": "特性",
      "nav.install": "安装",
      "nav.contact": "联系",
      "hero.tagline": "Your AI. Your Data. Your Machine.",
      "hero.lead":
        "一键获得你的本地个人 AI 助手——用你的算力、网络与工具，持久记住你，真正越来越懂你。",
      "hero.ctaGithub": "在 GitHub 查看",
      "hero.ctaInstall": "快速安装",
      "features.eyebrow": "产品设计",
      "features.title": "本地跑通，真正越来越懂你",
      "features.lead":
        "默认零账单、零账号门槛；数据与身份留本机。可选云端与联网增强，但始终有纯本地路径。",
      "features.f1.title": "完全本地化",
      "features.f1.body":
        "对话、记忆、检索、执行可纯本地跑通；算力默认本机，可选 API 增强。",
      "features.f2.title": "真正易用",
      "features.f2.body":
        "一键安装、立即可用；主路径只有 <code>la</code> · <code>la setup</code> · <code>la chat</code>。",
      "features.f3.title": "长期多层次记忆",
      "features.f3.body":
        "Hot / Warm / Cold + Mem0：记住你，也懂得该记什么、何时介入。",
      "features.f4.title": "本机工具",
      "features.f4.body":
        "本地 Shell、写文件、工作区感知；执行前确认，危险命令拦截。",
      "features.f5.title": "本地 RAG",
      "features.f5.body": "文档进知识库，对话时可深度召回原文。",
      "features.f6.title": "日常三剑客",
      "features.f6.body":
        "<code>la summarize</code> · <code>la news</code> · <code>la polish</code>——总结、资讯、润色一键搞定。",
      "install.eyebrow": "快速开始",
      "install.title": "一行命令，装上就聊",
      "install.lead": "需要 Python 3.10+ 与 pipx。当前版本 v0.4.0。",
      "install.copy": "复制",
      "install.copied": "已复制",
      "install.hint":
        "有 API → 写入 Key；无 API → <code>la setup -y</code> 装 Ollama。",
      "install.docs": "完整文档与升级说明 →",
      "contact.eyebrow": "联系",
      "contact.title": "打招呼",
      "contact.lead": "问题、建议或合作，欢迎来信或开 Issue。",
      "contact.emailLabel": "邮箱",
      "footer.line": "LocalAgent · MIT · v0.4.0",
      title: "LocalAgent — 本地个人 AI 助手",
      description:
        "LocalAgent — Your AI. Your Data. Your Machine. 一键获得本地个人 AI 助手。",
    },
    en: {
      "nav.features": "Features",
      "nav.install": "Install",
      "nav.contact": "Contact",
      "hero.tagline": "Your AI. Your Data. Your Machine.",
      "hero.lead":
        "One step to your local personal AI assistant — your compute, your network, your tools; lasting memory that truly gets to know you.",
      "hero.ctaGithub": "View on GitHub",
      "hero.ctaInstall": "Quick install",
      "features.eyebrow": "Product design",
      "features.title": "Fully local. Knows you long-term.",
      "features.lead":
        "Zero bill and zero account by default; identity and data stay on your machine. Optional cloud and web — always with a pure local path.",
      "features.f1.title": "Fully local",
      "features.f1.body":
        "Chat, memory, retrieval, and tools can run on-device; local compute by default, optional API boost.",
      "features.f2.title": "Truly easy",
      "features.f2.body":
        "One-step install, ready to talk. Main path: <code>la</code> · <code>la setup</code> · <code>la chat</code>.",
      "features.f3.title": "Layered long-term memory",
      "features.f3.body":
        "Hot / Warm / Cold + Mem0: remembers you — and knows what to keep, and when to step in.",
      "features.f4.title": "On-device tools",
      "features.f4.body":
        "Local shell, file writes, workspace awareness; confirm before run, block dangerous commands.",
      "features.f5.title": "Local RAG",
      "features.f5.body":
        "Ingest documents into a knowledge base; deep-recall source text in chat.",
      "features.f6.title": "Daily essentials",
      "features.f6.body":
        "<code>la summarize</code> · <code>la news</code> · <code>la polish</code> — docs, briefing, and copy in one shot.",
      "install.eyebrow": "Quick start",
      "install.title": "One command, then chat",
      "install.lead": "Needs Python 3.10+ and pipx. Current version v0.4.0.",
      "install.copy": "Copy",
      "install.copied": "Copied",
      "install.hint":
        "Have an API → set your key. No API → <code>la setup -y</code> for Ollama.",
      "install.docs": "Full docs & upgrade notes →",
      "contact.eyebrow": "Contact",
      "contact.title": "Say hello",
      "contact.lead":
        "Questions, ideas, or collaboration — email us or open an Issue.",
      "contact.emailLabel": "Email",
      "footer.line": "LocalAgent · MIT · v0.4.0",
      title: "LocalAgent — Local personal AI",
      description:
        "LocalAgent — Your AI. Your Data. Your Machine. A fully local personal AI assistant.",
    },
  };

  function detectLang() {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "zh" || saved === "en") return saved;
    const nav = (navigator.language || "").toLowerCase();
    return nav.startsWith("zh") ? "zh" : "en";
  }

  function applyLang(lang) {
    const dict = strings[lang] || strings.zh;
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
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
        lang === "zh" ? "assets/logo.zh-CN.png" : "assets/logo.png";
    }

    document.querySelectorAll(".lang-switch [data-lang]").forEach((btn) => {
      btn.classList.toggle("is-active", btn.getAttribute("data-lang") === lang);
    });

    localStorage.setItem(STORAGE_KEY, lang);
  }

  function setupLangSwitch() {
    document.querySelectorAll(".lang-switch [data-lang]").forEach((btn) => {
      btn.addEventListener("click", () => {
        applyLang(btn.getAttribute("data-lang"));
      });
    });
  }

  function setupCopy() {
    const btn = document.getElementById("copy-install");
    if (!btn) return;

    btn.addEventListener("click", async () => {
      const lang = localStorage.getItem(STORAGE_KEY) || detectLang();
      const dict = strings[lang] || strings.zh;
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

  applyLang(detectLang());
  setupLangSwitch();
  setupCopy();
})();
