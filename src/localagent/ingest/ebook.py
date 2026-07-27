"""MOBI / Kindle ebook extraction for ingest and summarize."""

from __future__ import annotations

import html
import re
import shutil
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

_SKIP_TAGS = frozenset({"script", "style", "noscript", "head"})
_BLOCK_TAGS = frozenset({"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"})
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_WS_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


class _MobiHtmlParser(HTMLParser):
    """Convert unpacked MOBI HTML into cite-friendly markdown-ish text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._in_heading = False
        self._heading_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in _HEADING_TAGS:
            self._in_heading = True
            self._heading_buf = []
        elif tag == "br":
            self._parts.append("\n")
        elif tag in _BLOCK_TAGS and self._parts and not self._parts[-1].endswith("\n"):
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in _HEADING_TAGS:
            title = "".join(self._heading_buf).strip()
            if title:
                self._parts.append(f"\n\n## [§{title}]\n")
            self._in_heading = False
            self._heading_buf = []
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = html.unescape(data)
        if not text.strip():
            return
        if self._in_heading:
            self._heading_buf.append(text)
        else:
            self._parts.append(text)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        lines = [_WS_RE.sub(" ", line).strip() for line in raw.splitlines()]
        text = "\n".join(line for line in lines if line)
        return _BLANK_LINES_RE.sub("\n\n", text).strip()


def html_to_chapter_text(html_content: str) -> str:
    """Parse MOBI HTML and inject ``## [§章节]`` markers for cite/segment."""
    parser = _MobiHtmlParser()
    parser.feed(html_content)
    parser.close()
    return parser.get_text()


def _load_extracted_html(path: Path) -> tuple[str, dict]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = html_to_chapter_text(raw)
    chapter_markers = text.count("## [§")
    return text, {"mobi_extract_type": "html", "chapter_markers": chapter_markers}


def _load_extracted_epub(path: Path) -> tuple[str, dict]:
    parts: list[str] = []
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        container_xml = zf.read("META-INF/container.xml")
        root = ElementTree.fromstring(container_xml)
        opf_path = ""
        for elem in root.iter():
            if elem.tag.endswith("rootfile"):
                opf_path = elem.attrib.get("full-path", "")
                break
        if not opf_path:
            raise ValueError("EPUB container.xml missing rootfile")

        opf_root = ElementTree.fromstring(zf.read(opf_path))
        opf_dir = Path(opf_path).parent
        ns = {"opf": "http://www.idpf.org/2007/opf"}

        manifest: dict[str, str] = {}
        for item in opf_root.findall(".//opf:manifest/opf:item", ns):
            item_id = item.attrib.get("id", "")
            href = item.attrib.get("href", "")
            if item_id and href:
                manifest[item_id] = str((opf_dir / href).as_posix())

        spine_hrefs: list[str] = []
        for itemref in opf_root.findall(".//opf:spine/opf:itemref", ns):
            ref = itemref.attrib.get("idref", "")
            href = manifest.get(ref, "")
            if href:
                spine_hrefs.append(href)

        for href in spine_hrefs:
            if href not in names:
                candidates = [n for n in names if n.endswith(Path(href).name)]
                if not candidates:
                    continue
                href = candidates[0]
            raw = zf.read(href).decode("utf-8", errors="replace")
            chunk = html_to_chapter_text(raw)
            if chunk:
                parts.append(chunk)

    text = "\n\n".join(parts).strip()
    return text, {"mobi_extract_type": "epub", "chapter_markers": text.count("## [§")}


def load_epub(path: Path) -> tuple[str, dict]:
    """Read an unencrypted EPUB file and return plain text + metadata."""
    try:
        text, meta = _load_extracted_epub(path)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"EPUB 文件格式损坏或不是有效 zip: {path}") from exc
    except ElementTree.ParseError as exc:
        raise ValueError(f"EPUB 内部 XML 解析失败: {path}") from exc
    except Exception as exc:
        msg = str(exc).lower()
        if "drm" in msg or "encrypt" in msg or "password" in msg:
            raise ValueError("EPUB 文件可能受 DRM 加密，无法读取") from exc
        raise

    meta = {"ebook_format": "epub", **meta}
    return text, meta


def explain_epub_load_failure(path: Path) -> str:
    """User-facing hint when EPUB load fails."""
    try:
        text, _meta = load_epub(path)
        if not text.strip():
            return f"EPUB 解压成功但正文为空: {path}"
    except ValueError as exc:
        return str(exc)
    except Exception:
        return f"无法读取 EPUB 文件（可能为 DRM 加密或格式损坏）: {path}"
    return f"无法读取 EPUB 文件: {path}"


def load_mobi(path: Path) -> tuple[str, dict]:
    """Unpack an unencrypted MOBI file and return plain text + metadata."""
    try:
        import mobi
    except ImportError as exc:
        raise RuntimeError("MOBI 支持需要 mobi 库，请重新安装 la-localagent") from exc

    tempdir: str | None = None
    try:
        tempdir, extracted = mobi.extract(str(path))
        extracted_path = Path(extracted)
        if not extracted_path.exists():
            raise ValueError(f"mobi.extract 未产生可读文件: {extracted}")

        suffix = extracted_path.suffix.lower()
        if suffix in {".html", ".htm", ".xhtml"}:
            text, meta = _load_extracted_html(extracted_path)
        elif suffix == ".pdf":
            from localagent.ingest.loader import _load_pdf

            text, meta = _load_pdf(extracted_path)
            meta = {"mobi_extract_type": "pdf", **meta}
        elif suffix == ".epub":
            text, meta = _load_extracted_epub(extracted_path)
        else:
            raise ValueError(f"不支持的 MOBI 解压格式 {suffix!r}")

        return text, meta
    except Exception as exc:
        msg = str(exc).lower()
        if "drm" in msg or "encrypt" in msg or "password" in msg:
            raise ValueError("MOBI 文件可能受 DRM 加密，无法读取") from exc
        raise
    finally:
        if tempdir:
            shutil.rmtree(tempdir, ignore_errors=True)


def explain_mobi_load_failure(path: Path) -> str:
    """User-facing hint when MOBI load fails."""
    try:
        text, _meta = load_mobi(path)
        if not text.strip():
            return f"MOBI 解压成功但正文为空: {path}"
    except ValueError as exc:
        return str(exc)
    except RuntimeError as exc:
        return str(exc)
    except Exception:
        return f"无法读取 MOBI 文件（可能为 DRM 加密或格式损坏）: {path}"
    return f"无法读取 MOBI 文件: {path}"
