"""One-click document summarize — short-path first (1–3 sentences + cited bullets)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from localagent import config
from localagent.audit.security import is_sensitive_path, sensitive_path_reason
from localagent.ingest.chunker import split_into_sections
from localagent.ingest.loader import LoadedDoc, load_file

KEEP_HINT = (
    "默认不入库（瞬时读懂）。需要收藏到知识库时："
    "文档对话内输入 /keep，或启动时加 --keep / `la summarize <path> --no-chat --keep`。"
)

_CITE_RE = re.compile(
    r"〔[^〕]+〕"
    r"|\[p\.\d+\]"
    r"|〔?§[^\s，,;；|〕\]]+"
    r"|Sheet\s*[:：]?\s*\S+"
    r"|p\.\d+",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(r"^\s*[-*•]\s+")
_HEADING_SUM = re.compile(r"^##\s*总结")
_HEADING_POINTS = re.compile(r"^##\s*结构化要点")
_HEADING_NOTE = re.compile(r"^##\s*需要注意")
_HEADING_ASK = re.compile(r"^##\s*你可以接着问")


class SummarizeError(ValueError):
    """User-facing summarize failure."""


class DocumentTooLongError(SummarizeError):
    """Document exceeds short-path card limit when long-path/RAG is disabled."""


@dataclass
class SummarizeResult:
    markdown: str
    path: Path
    filename: str
    char_count: int
    page_count: int | None = None
    kept: bool = False
    keep_target: Path | None = None
    used_llm: bool = False
    warnings: list[str] = field(default_factory=list)
    annotated_text: str = ""
    session_source_key: str = ""

    def render(self) -> str:
        return self.markdown

    @property
    def uses_retrieval(self) -> bool:
        """Prefer scoped RAG when body exceeds prompt-stuffing budget or key is set for long docs."""
        if not (self.session_source_key or "").strip():
            return False
        return self.char_count > config.SUMMARIZE_LLM_INPUT_CHARS


def _suffix_ok(path: Path) -> bool:
    return path.suffix.lower() in config.SUMMARIZE_SUFFIXES


def _annotate_for_cite(doc: LoadedDoc) -> str:
    """Ensure the model sees explicit § / p. anchors."""
    suffix = str(doc.metadata.get("suffix") or Path(doc.filename).suffix).lower()
    text = doc.text or ""
    if suffix == ".pdf":
        # loader already injects ## [p.N]
        return text
    if suffix == ".xlsx":
        # Normalize sheet headers to cite-friendly markers.
        return re.sub(
            r"(?m)^##\s*Sheet:\s*(.+?)\s*$",
            lambda m: f"## [§{m.group(1).strip()}]",
            text,
        )
    # md / txt: wrap sections from chunker
    sections = split_into_sections(text, filename=doc.filename)
    if not sections:
        return text
    if len(sections) == 1 and sections[0].heading in {"(全文)", ""}:
        body = sections[0].text.strip()
        return f"## [§全文]\n{body}" if body else text
    parts: list[str] = []
    for section in sections:
        title = section.heading.lstrip("# ").strip() or "section"
        if title.startswith("[§") or title.startswith("[p."):
            marker = title if title.startswith("#") else f"## {title}"
        else:
            marker = f"## [§{title}]"
        body = section.text.strip()
        # Avoid duplicating the heading line already inside section.text
        if body.startswith(section.heading):
            lines = body.splitlines()
            body = "\n".join(lines[1:]).strip()
        parts.append(f"{marker}\n{body}" if body else marker)
    return "\n\n".join(parts)


def _prompt(annotated: str, *, filename: str) -> str:
    return (
        "你是文档速读助手。根据下列带索引标记的原文，输出「3 分钟读懂」卡片。\n"
        "硬性规则：\n"
        "1. 「总结」用 1～最多 3 句话；能一句说清就一句，禁止凑满三条或注水。\n"
        "2. 「结构化要点」5～8 条；每条必须带具体索引，格式强制为 "
        "〔§章节 | p.页〕或 〔§章节〕或 〔p.页〕"
        "（Markdown 用章节；PDF 尽量同时给章节与页；表格用 §Sheet名）。\n"
        "3. 索引必须来自原文中的 [§…] / [p.…] 标记，禁止编造页码或章节。\n"
        "4. 找不到依据的要点宁可省略，也不要瞎写索引。\n"
        "5. 「需要注意」仅在有局限/免责/反方观点时写；否则整节省略。\n"
        "6. 「你可以接着问」给 2～3 个短问题，且必须是原文已覆盖、可继续追问的点；"
        "原文只有导语/摘要时请整节省略该段，禁止编造机制/架构细节类问题。\n"
        "7. 只输出 Markdown，不要前言后语。\n\n"
        "输出模板：\n"
        "## 总结（最多三句话）\n"
        "…\n\n"
        "## 结构化要点\n"
        "- **要点**：… — 依据：… 〔§… | p.…〕\n\n"
        "## 需要注意\n"
        "- …\n\n"
        "## 你可以接着问\n"
        "1. …\n\n"
        f"文件名: {filename}\n\n"
        f"原文（含索引标记）:\n{annotated}"
    )


def _strip_marker_noise(text: str) -> str:
    """Remove cite markers / markdown headings from prose snippets."""
    cleaned = re.sub(r"(?m)^#{1,6}\s*", "", text or "")
    cleaned = re.sub(r"\[§[^\]]+\]|\[p\.\d+\]", "", cleaned)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned


def _cite_from_heading(heading: str) -> str:
    title = (heading or "").lstrip("# ").strip() or "全文"
    if title.startswith("[") and title.endswith("]"):
        inner = title[1:-1]
        return inner if inner.startswith(("§", "p.")) else f"§{inner}"
    if title.startswith(("§", "p.")):
        return title
    return f"§{title}"


def _heuristic_summary(annotated: str, *, filename: str) -> str:
    """Offline fallback when LLM is unavailable."""
    sections = split_into_sections(annotated, filename=filename)
    prose = _strip_marker_noise(annotated)
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[。！？.!?])\s+", prose)
        if s.strip() and len(s.strip()) > 8
    ]
    lead = sentences[0] if sentences else f"文档 {filename} 的要点如下。"
    if len(lead) > 160:
        lead = lead[:159] + "…"
    lines = ["## 总结（最多三句话）", lead, "", "## 结构化要点"]
    count = 0
    for section in sections:
        if count >= 6:
            break
        cite = _cite_from_heading(section.heading)
        body = _strip_marker_noise(section.text)
        # Drop duplicated heading title at start of body
        title_plain = cite.lstrip("§").lstrip("p.").strip()
        if body.startswith(title_plain):
            body = body[len(title_plain) :].lstrip(" ：:>-").strip()
        if not body:
            continue
        snippet = body[:120] + ("…" if len(body) > 120 else "")
        label = title_plain or cite
        lines.append(f"- **{label}**：{snippet} — 依据：原文 〔{cite}〕")
        count += 1
    if count == 0:
        lines.append(f"- **全文**：{lead} — 依据：原文 〔§全文〕")
    lines.extend(["", "## 你可以接着问", "1. 哪一节最值得展开？", "2. 有哪些需要注意的限制？"])
    return "\n".join(lines)


def _strip_fence(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:markdown|md)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def citation_ok(line: str) -> bool:
    return bool(_CITE_RE.search(line))


def ensure_citations(markdown: str) -> tuple[str, list[str]]:
    """Append honest missing-cite markers; never invent page numbers."""
    warnings: list[str] = []
    lines = markdown.splitlines()
    out: list[str] = []
    in_points = False
    fixed = 0
    for line in lines:
        if _HEADING_POINTS.match(line):
            in_points = True
            out.append(line)
            continue
        if line.startswith("## "):
            in_points = False
            out.append(line)
            continue
        if in_points and _BULLET_RE.match(line) and not citation_ok(line):
            out.append(line.rstrip() + " 〔未定位到页/节〕")
            fixed += 1
            continue
        out.append(line)
    if fixed:
        warnings.append(f"{fixed} 条要点缺少可核对索引，已标注「未定位到页/节」")
    return "\n".join(out).strip() + "\n", warnings


def count_summary_sentences(markdown: str) -> int:
    """Count sentences in the 总结 section (for tests / soft checks)."""
    lines = markdown.splitlines()
    collecting = False
    parts: list[str] = []
    for line in lines:
        if _HEADING_SUM.match(line):
            collecting = True
            continue
        if collecting and line.startswith("## "):
            break
        if collecting and line.strip():
            parts.append(line.strip())
    blob = " ".join(parts)
    sentences = [s for s in re.split(r"(?<=[。！？.!?])\s+", blob) if s.strip()]
    # Numbered lines "1. …" also count as sentences
    if not sentences and parts:
        return len(parts)
    return len(sentences)


def _llm_summarize(annotated: str, *, filename: str) -> str | None:
    try:
        from localagent.models.router import ChatMessage, get_model_router
    except Exception:
        return None
    clipped = annotated[: config.SUMMARIZE_LLM_INPUT_CHARS]
    try:
        reply = get_model_router().chat(
            [ChatMessage(role="user", content=_prompt(clipped, filename=filename))],
            temperature=0.2,
            usage_command="summarize",
        )
    except Exception:
        return None
    text = _strip_fence(reply or "")
    if not text or "##" not in text:
        return None
    return text


def summarize_loaded(
    doc: LoadedDoc,
    *,
    use_llm: bool = True,
    allow_long: bool = False,
) -> SummarizeResult:
    annotated = _annotate_for_cite(doc)
    char_count = len(annotated)
    warnings: list[str] = []
    if char_count > config.SUMMARIZE_SHORT_MAX_CHARS and not allow_long:
        raise DocumentTooLongError(
            f"文档约 {char_count} 字，超出短总结上限（{config.SUMMARIZE_SHORT_MAX_CHARS}）。"
            "请拆成章节后重试，或提高 LA_SUMMARIZE_SHORT_MAX_CHARS。"
        )
    if char_count > config.SUMMARIZE_SHORT_MAX_CHARS and allow_long:
        warnings.append(
            f"文档约 {char_count} 字，速读卡基于截断输入；深聊将按片段检索全文"
        )
        annotated_for_card = annotated[: config.SUMMARIZE_LLM_INPUT_CHARS]
    else:
        annotated_for_card = annotated

    used_llm = False
    markdown: str | None = None
    if use_llm:
        markdown = _llm_summarize(annotated_for_card, filename=doc.filename)
        if markdown:
            used_llm = True
            # Soft retry once if points lack citations
            if "## 结构化要点" in markdown:
                point_lines = []
                grab = False
                for line in markdown.splitlines():
                    if _HEADING_POINTS.match(line):
                        grab = True
                        continue
                    if grab and line.startswith("## "):
                        break
                    if grab and _BULLET_RE.match(line):
                        point_lines.append(line)
                missing = sum(1 for line in point_lines if not citation_ok(line))
                if point_lines and missing >= max(1, len(point_lines) // 2):
                    retry = _llm_summarize(
                        annotated_for_card
                        + "\n\n【重试】上轮要点缺少 〔§…|p.…〕索引，请重写并确保每条都有索引。",
                        filename=doc.filename,
                    )
                    if retry:
                        markdown = retry

    if not markdown:
        markdown = _heuristic_summary(annotated_for_card, filename=doc.filename)
        warnings.append("模型摘要不可用，已使用本地启发式摘要")

    markdown, cite_warnings = ensure_citations(markdown)
    warnings.extend(cite_warnings)

    page_count = doc.metadata.get("page_count")
    if isinstance(page_count, int):
        pages: int | None = page_count
    else:
        pages = None

    return SummarizeResult(
        markdown=markdown,
        path=Path(doc.source),
        filename=doc.filename,
        char_count=char_count,
        page_count=pages,
        used_llm=used_llm,
        warnings=warnings,
        annotated_text=annotated,
    )


def summarize_path(
    path: str | Path,
    *,
    keep: bool = False,
    use_llm: bool = True,
) -> SummarizeResult:
    source = Path(path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise SummarizeError(f"文件不存在: {source}")
    if is_sensitive_path(source):
        raise SummarizeError(sensitive_path_reason(source) or "敏感路径，拒绝读取")
    if not _suffix_ok(source):
        supported = ", ".join(sorted(config.SUMMARIZE_SUFFIXES))
        raise SummarizeError(f"不支持的文件类型 {source.suffix!r}；支持: {supported}")

    doc = load_file(source)
    if doc is None:
        raise SummarizeError(
            f"无法读取文件内容（空文件、扫描版 PDF 无文本层，或解析失败）: {source}"
        )

    result = summarize_loaded(doc, use_llm=use_llm, allow_long=True)

    try:
        from localagent.summarize.session_index import (
            index_document_session,
            summarize_source_key,
        )

        key = summarize_source_key(source)
        index_document_session(key, result.annotated_text, title=result.filename)
        result.session_source_key = key
    except Exception as exc:  # pragma: no cover
        result.warnings.append(f"会话向量化跳过: {exc}")

    if keep:
        from localagent.ingest.add_file import add_file

        target, _ingest = add_file(source)
        result.kept = True
        result.keep_target = target

    return result


def summarize_document_tool(path: str, *, keep: bool = False, cwd: str | None = None) -> str:
    """Agent tool entry: summarize a local document; default not kept."""
    raw = (path or "").strip()
    if not raw:
        return "错误: 请提供 path。"
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute() and cwd:
        candidate = Path(cwd).expanduser() / candidate
    try:
        result = summarize_path(candidate, keep=keep, use_llm=True)
    except DocumentTooLongError as exc:
        return f"错误: {exc}\n提示: {KEEP_HINT}"
    except SummarizeError as exc:
        return f"错误: {exc}"
    except Exception as exc:  # pragma: no cover - unexpected I/O
        return f"错误: 总结失败: {exc}"

    parts = [result.markdown.rstrip(), ""]
    if result.warnings:
        parts.append("（" + "；".join(result.warnings) + "）")
    if result.kept:
        parts.append(f"已入库: {result.keep_target}")
    else:
        parts.append(f"未入库。{KEEP_HINT}")
    return "\n".join(parts)


def format_document_context(
    result: SummarizeResult,
    *,
    max_chars: int | None = None,
    retrieval_block: str = "",
    include_full_body: bool | None = None,
) -> str:
    """Build a system-prompt block for document-focused follow-up chat.

    Short docs: stuff annotated body. Long / RAG sessions: card + retrieval hits.
    """
    limit = max_chars if max_chars is not None else config.SUMMARIZE_LLM_INPUT_CHARS
    body = (result.annotated_text or "").strip()
    use_full = include_full_body
    if use_full is None:
        use_full = not result.uses_retrieval
    if use_full and len(body) > limit:
        body = body[: limit - 1] + "…"
    kept_line = (
        f"已入库 → {result.keep_target}"
        if result.kept and result.keep_target
        else "未入库（默认；用户明确要求时可用会话内 /keep）"
    )
    rules = (
        "规则: 你已在文档对话中，围绕本文件深入解答；"
        "禁止建议用户再运行 la summarize / 进入文档对话；"
        "不要主动追问是否入库；用户说入库/进知识库时告知可用 /keep；"
        "若检索/原文未覆盖细节，如实说明依据不足，禁止编造，也禁止为此调用 reflect_memory。"
    )
    parts = [
        "[当前文档 · 聚焦会话（已预加载，请优先据此回答；引用时用 〔§…|p.…〕）]",
        f"文件: {result.path}",
        f"入库状态: {kept_line}",
    ]
    if result.session_source_key:
        parts.append(f"会话索引: {result.session_source_key}")
    parts.extend(
        [
            rules,
            "",
            "## 速读卡",
            result.markdown.strip(),
        ]
    )
    if retrieval_block.strip():
        parts.extend(["", retrieval_block.strip()])
    elif use_full:
        parts.extend(["", "## 原文（含索引标记）", body or "（无原文文本）"])
    else:
        parts.extend(
            [
                "",
                "## 原文",
                "（正文较长，本轮未塞入全文；请依据上方检索片段与速读卡回答）",
            ]
        )
    return "\n".join(parts)


def not_kept_hint_if_asked(user_message: str) -> str | None:
    """Reactive tip when user asks why a summarized doc is missing from KB."""
    text = (user_message or "").strip()
    if not text:
        return None
    ask = bool(
        re.search(
            r"(为啥|为什么|为何).{0,12}(没|不).{0,8}(入库|进知识库|进库|索引)"
            r"|(总结|一键总结).{0,16}(搜不到|找不到|没有入库|没入库|未入库)"
            r"|(刚才|之前).{0,12}(总结|一键总结).{0,16}(知识库|入库)",
            text,
        )
    )
    if not ask:
        return None
    return KEEP_HINT
