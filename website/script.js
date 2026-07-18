(() => {
  // v3: English-first. Ignore legacy auto-detect / sticky zh caches.
  const STORAGE_KEY = "la-site-lang-v3";
  const LEGACY_STORAGE_KEYS = ["la-site-lang", "la-site-lang-v2"];
  const INSTALL_CMD =
    'pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"\nla';

  const DEMO_IDS = ["setup", "memory", "deepread"];

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
        "装上就能聊、能记住、能动手办事——默认本机跑通，云端可选增强；你的身份与数据不离开本机。",
      "features.f1.title": "Local First",
      "features.f1.body":
        "默认零账单路径：对话、记忆、检索、工具可纯本地跑通。主路径 <code>la</code> · <code>la setup</code> · <code>la chat</code>。可选云端——身份与数据留本机。",
      "features.f1.link": "看「零成本上手」演示 →",
      "features.f2.title": "Memory Forever",
      "features.f2.body":
        "Hot / Warm / Cold + Mem0 跨会话持久。记住你，也懂得该记什么、别记什么、何时介入。文档进本地知识库，深度召回原文。",
      "features.f2.link": "看「真记住你」演示 →",
      "features.f3.title": "Actions Automated",
      "features.f3.body":
        "Shell、写文件、工作区；summarize · news · polish；定时简报。执行前确认，危险硬拦，办完有回执。",
      "features.f3.link": "看「文章深聊」演示 →",
      "demo.eyebrow": "演示",
      "demo.title": "三件事，马上感受到",
      "demo.lead":
        "短片预览，不接云端推理。装上本机后，这些就是真实路径。",
      "demo.tab.setup": "上手",
      "demo.tab.memory": "记住你",
      "demo.tab.deepread": "深聊",
      "demo.moreTour": "完整产品漫游 →",
      "demo.moreInstall": "去安装 →",
      "demo.setup.title": "本机一键，默认可零成本",
      "demo.setup.body":
        "不绑账号也能聊；算力和数据都在你机器上。",
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
        "summarize 与 news 精读共用 DocumentChat，不是另开一个空聊天框。",
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
      "contact.lead":
        "不是又一个 Chat 客户端——本地 AI：记得住你，也能把事办完。问题、建议或合作，欢迎来信。",
      "contact.emailLabel": "邮箱",
      "footer.line": "LocalAgent · MIT · v0.4.0",
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
        "Install and you’re chatting, remembered, and getting work done — on-device by default, cloud optional; your identity and data stay on your machine.",
      "features.f1.title": "Local First",
      "features.f1.body":
        "Zero-bill default path: chat, memory, retrieval, and tools run on-device. Main path: <code>la</code> · <code>la setup</code> · <code>la chat</code>. Optional cloud — identity and data stay local.",
      "features.f1.link": "See the zero-cost setup demo →",
      "features.f2.title": "Memory Forever",
      "features.f2.body":
        "Hot / Warm / Cold + Mem0 across sessions. Remembers you — and knows what to keep, what to drop, and when to step in. Docs go into a local KB for deep recall.",
      "features.f2.link": "See the “remembers you” demo →",
      "features.f3.title": "Actions Automated",
      "features.f3.body":
        "Shell, file writes, workspace; summarize · news · polish; scheduled brief. Confirm before side effects, block danger, show a receipt when done.",
      "features.f3.link": "See the deep-read demo →",
      "demo.eyebrow": "Demo",
      "demo.title": "Three moments you can feel",
      "demo.lead":
        "Short clips — no hosted model. On your machine, these are the real paths.",
      "demo.tab.setup": "Setup",
      "demo.tab.memory": "Memory",
      "demo.tab.deepread": "Deep read",
      "demo.moreTour": "Full product tour →",
      "demo.moreInstall": "Install →",
      "demo.setup.title": "One step local. Zero bill by default.",
      "demo.setup.body":
        "No account required to chat. Compute and data stay on your machine.",
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
        "summarize and news deep-read share DocumentChat — not a blank new thread.",
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
        "Not another chat client — local AI that remembers and gets things done. Questions, ideas, or collaboration welcome.",
      "contact.emailLabel": "Email",
      "footer.line": "LocalAgent · MIT · v0.4.0",
      title: "LocalAgent — Local AI that remembers and gets things done",
      description:
        "LocalAgent — Local First. Memory Forever. Actions Automated. Local AI that remembers and gets things done.",
    },
  };

  let currentLang = "en";
  let activeDemo = "setup";

  function preferredLang() {
    try {
      for (const key of LEGACY_STORAGE_KEYS) {
        localStorage.removeItem(key);
      }
      const saved = localStorage.getItem(STORAGE_KEY);
      // Only honor an explicit manual choice; otherwise English-first.
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

  function syncDemoVideo() {
    const video = document.getElementById("demo-video");
    const source = document.getElementById("demo-video-src");
    if (!video || !source) return;

    const base = demoAssetBase(currentLang, activeDemo);
    const nextSrc = `${base}.mp4`;
    const nextPoster = `${base}.poster.jpg`;
    const currentSrc = source.getAttribute("src") || "";

    video.setAttribute("poster", nextPoster);
    if (currentSrc !== nextSrc) {
      source.setAttribute("src", nextSrc);
      video.load();
    }

    if (prefersReducedMotion()) {
      video.pause();
      video.removeAttribute("autoplay");
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

  function renderDemoAside() {
    const dict = strings[currentLang] || strings.en;
    const title = document.getElementById("demo-aside-title");
    const body = document.getElementById("demo-aside-body");
    const note = document.getElementById("demo-aside-note");
    if (title) title.textContent = dict[`demo.${activeDemo}.title`];
    if (body) body.textContent = dict[`demo.${activeDemo}.body`];
    if (note) note.textContent = dict[`demo.${activeDemo}.note`];
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

  function renderDemo() {
    renderDemoTabs();
    renderDemoAside();
    syncDemoVideo();
  }

  function scrollDemoIntoView() {
    const root = document.getElementById("demo");
    if (!root) return;
    root.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function setDemo(id, { updateHash = true, scroll = false } = {}) {
    if (!DEMO_IDS.includes(id)) return;
    activeDemo = id;
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

    if (typeof window.matchMedia === "function") {
      const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
      const onChange = () => syncDemoVideo();
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
