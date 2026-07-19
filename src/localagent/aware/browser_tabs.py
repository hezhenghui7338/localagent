"""Read currently open browser tabs (macOS AppleScript / JXA)."""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import dataclass, field
from typing import Any

from localagent.i18n import t


@dataclass
class BrowserNow:
    browser: str
    windows: int = 0
    tabs: int = 0
    active_title: str = ""
    active_url: str = ""
    frontmost: bool = False
    items: list[dict[str, str]] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "browser": self.browser,
            "windows": self.windows,
            "tabs": self.tabs,
            "active_title": self.active_title,
            "active_url": self.active_url,
            "frontmost": self.frontmost,
            "items": list(self.items),
            "error": self.error,
        }


_JXA = r"""
function run() {
  var apps = [
    {name: "Google Chrome", id: "chrome"},
    {name: "Chromium", id: "chromium"},
    {name: "Brave Browser", id: "brave"},
    {name: "Microsoft Edge", id: "edge"},
    {name: "Safari", id: "safari"}
  ];
  var out = [];
  for (var a = 0; a < apps.length; a++) {
    var spec = apps[a];
    try {
      var app = Application(spec.name);
      if (!app.running()) continue;
      var isFrontmost = false;
      try { isFrontmost = !!app.frontmost(); } catch (ef) { isFrontmost = false; }
      var windows = app.windows();
      var items = [];
      var activeTitle = "";
      var activeUrl = "";
      // Prefer the browser's front window (index === 1); fall back to windows[0].
      var frontWi = 0;
      for (var fi = 0; fi < windows.length; fi++) {
        try {
          if (Number(windows[fi].index()) === 1) { frontWi = fi; break; }
        } catch (eIdx) {}
      }
      for (var wi = 0; wi < windows.length; wi++) {
        var w = windows[wi];
        var tabs = [];
        try { tabs = w.tabs(); } catch (e1) { continue; }
        var activeIdx = 0;
        try {
          if (spec.id === "safari") {
            activeIdx = w.currentTab().index() - 1;
          } else {
            activeIdx = w.activeTabIndex() - 1;
          }
        } catch (e2) { activeIdx = 0; }
        for (var ti = 0; ti < tabs.length; ti++) {
          var t = tabs[ti];
          var title = "";
          var url = "";
          try { title = String(t.name() || ""); } catch (e3) {}
          try { url = String(t.url() || ""); } catch (e4) {}
          var active = (ti === activeIdx && wi === frontWi);
          items.push({title: title, url: url, active: active});
          if (active) {
            activeTitle = title;
            activeUrl = url;
          }
        }
      }
      if (items.length || windows.length) {
        out.push({
          browser: spec.id,
          windows: windows.length,
          tabs: items.length,
          active_title: activeTitle,
          active_url: activeUrl,
          frontmost: isFrontmost,
          items: items.slice(0, 40)
        });
      }
    } catch (err) {}
  }
  return JSON.stringify(out);
}
"""


def collect_open_tabs() -> list[BrowserNow]:
    """Best-effort current tabs. Non-macOS returns a single unsupported stub."""
    if platform.system() != "Darwin":
        return [
            BrowserNow(
                browser="-",
                error=t("aware.tabs_unsupported"),
            )
        ]
    try:
        proc = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", _JXA],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [BrowserNow(browser="-", error=t("aware.tabs_osascript_fail", exc=exc))]

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or t("aware.tabs_unknown_err")).strip()
        return [
            BrowserNow(
                browser="-",
                error=t(
                    "aware.tabs_error_with_hint",
                    err=err,
                    hint=t("aware.tabs_permission_hint"),
                ),
            )
        ]

    text = (proc.stdout or "").strip()
    if not text:
        return [
            BrowserNow(
                browser="-",
                error=t("aware.tabs_no_browser"),
            )
        ]
    try:
        rows = json.loads(text)
    except json.JSONDecodeError:
        return [BrowserNow(browser="-", error=t("aware.tabs_parse_fail"))]

    out: list[BrowserNow] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        items = []
        for it in list(row.get("items") or [])[:40]:
            if isinstance(it, dict):
                items.append(
                    {
                        "title": str(it.get("title") or ""),
                        "url": str(it.get("url") or ""),
                        "active": "1" if it.get("active") else "",
                    }
                )
        out.append(
            BrowserNow(
                browser=str(row.get("browser") or ""),
                windows=int(row.get("windows") or 0),
                tabs=int(row.get("tabs") or 0),
                active_title=str(row.get("active_title") or ""),
                active_url=str(row.get("active_url") or ""),
                frontmost=bool(row.get("frontmost")),
                items=items,
            )
        )
    if not out:
        return [
            BrowserNow(
                browser="-",
                error=t("aware.tabs_no_browser"),
            )
        ]
    return out
