#!/usr/bin/env python3
import argparse
import base64
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.lexers.special import TextLexer
from pygments.util import ClassNotFound

APP_LABEL = "Codex"
HTML_TAB_TITLE = "chathistory"
FAVICON_PATH = Path(__file__).resolve().parent / "assets" / "f00f-150x150.png"
DEFAULT_COLLAPSE_LINE_THRESHOLD = 15
DEFAULT_COLLAPSED_VISIBLE_LINES = 8
CODE_FORMATTER = HtmlFormatter(style="native", cssclass="codehilite")
CODE_STYLE = CODE_FORMATTER.get_style_defs(".codehilite")
FENCED_BLOCK_RE = re.compile(r"```([\w.+-]*)\n(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
INLINE_TOKEN_RE = re.compile(r"\x00TOKEN(\d+)\x00")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


@dataclass(slots=True)
class RenderOptions:
    output: str | None = None
    chrome_path: str = os.environ.get("CHROME_BIN", "google-chrome")
    title: str | None = None
    tags: str | None = None
    pdf: bool = False
    plaintext: bool = False
    keep_html: str | None = None
    full: bool = False
    include_turn_context: bool = False
    include_events: bool = False
    collapse_threshold: int = DEFAULT_COLLAPSE_LINE_THRESHOLD
    collapse_lines: int = DEFAULT_COLLAPSED_VISIBLE_LINES


@dataclass(slots=True)
class PreviewEntry:
    role: str
    timestamp: str
    body: str

STYLE = f"""
:root {{
  color-scheme: light;
  --bg: #f5f2ea;
  --paper: #fffdf8;
  --ink: #1f2328;
  --muted: #667085;
  --line: #d8d0c2;
  --user: #f8e6ee;
  --assistant: #eef6ff;
  --developer: #fff4d6;
  --tool: #f6f7f9;
  --accent: #984d00;
  --code-bg: #1b2230;
  --code-line: #2e3a52;
  --code-text: #e6edf3;
  --inline-code-bg: #efe7d8;
  --inline-code-line: #d8c7ab;
  --inline-code-text: #5f370e;
}}
* {{ box-sizing: border-box; }}
@page {{
  size: A4;
  margin: 14mm 12mm 16mm;
}}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: "DejaVu Sans", Arial, sans-serif;
  line-height: 1.5;
  font-size: 12px;
}}
main {{
  max-width: 880px;
  margin: 0 auto;
  padding: 24px 18px 40px;
}}
header {{
  margin-bottom: 14px;
  padding: 0;
}}
header h1 {{
  margin: 0 0 10px;
  font-size: 24px;
}}
.summary {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}}
.chip {{
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 4px 10px;
  background: rgba(255,255,255,0.75);
  color: var(--muted);
  font-size: 11px;
}}
.tags {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  color: var(--accent);
  font-size: 11px;
  font-weight: 600;
}}
.tag {{
  display: inline-block;
}}
.entry {{
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 12px 14px;
  background: var(--paper);
  margin-bottom: 8px;
  break-inside: auto;
  page-break-inside: auto;
}}
.entry.keep-together {{
  break-inside: avoid-page;
  page-break-inside: avoid;
}}
.entry.user {{ background: var(--user); }}
.entry.assistant {{ background: var(--assistant); }}
.entry.developer {{ background: var(--developer); }}
.entry.tool, .entry.reasoning, .entry.system {{ background: var(--tool); }}
.meta {{
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 11px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  break-after: avoid-page;
  page-break-after: avoid;
}}
.label {{
  color: var(--accent);
  font-weight: 700;
}}
.body {{
  word-break: break-word;
  orphans: 2;
  widows: 2;
}}
.entry-collapsible .body {{
  --collapsed-lines: {DEFAULT_COLLAPSED_VISIBLE_LINES};
}}
.collapse-content {{
  position: relative;
}}
.entry-collapsible .collapse-content {{
  transition: max-height 160ms ease;
}}
.entry-collapsible.is-collapsed .collapse-content {{
  max-height: calc(var(--collapsed-lines) * 1.5em);
  overflow: hidden;
}}
.entry-collapsible.is-collapsed .collapse-content::after {{
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2.8em;
  background: linear-gradient(to bottom, rgba(255,255,255,0), rgba(255,253,248,0.96));
  pointer-events: none;
}}
.entry.user.entry-collapsible.is-collapsed .collapse-content::after {{
  background: linear-gradient(to bottom, rgba(248,230,238,0), rgba(248,230,238,0.96));
}}
.entry.assistant.entry-collapsible.is-collapsed .collapse-content::after {{
  background: linear-gradient(to bottom, rgba(238,246,255,0), rgba(238,246,255,0.96));
}}
.collapse-toggle {{
  margin-top: 10px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--accent);
  font: inherit;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}}
.collapse-toggle:hover {{
  text-decoration: underline;
}}
.collapse-toggle:focus-visible {{
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: 4px;
}}
.message-text {{
  margin: 0 0 10px;
  white-space: pre-wrap;
}}
.message-text:last-child {{
  margin-bottom: 0;
}}
.message-text strong {{
  font-weight: 700;
}}
.message-text em {{
  font-style: italic;
}}
.message-link {{
  color: #0b62d6;
  font-weight: 500;
  text-decoration: none;
}}
.file-link {{
  font-weight: 600;
}}
.file-link {{
  font-weight: 600;
}}
.message-heading {{
  margin: 0 0 10px;
  font-weight: 700;
  line-height: 1.3;
}}
.message-heading.h1 {{ font-size: 1.5em; }}
.message-heading.h2 {{ font-size: 1.3em; }}
.message-heading.h3 {{ font-size: 1.15em; }}
.message-list {{
  margin: 0 0 10px 18px;
  padding: 0;
}}
.message-list:last-child {{
  margin-bottom: 0;
}}
.message-list li {{
  margin: 0 0 4px;
}}
.image-card {{
  margin: 10px 0 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: rgba(255,255,255,0.72);
  overflow: hidden;
}}
.image-label {{
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
}}
.image-card img {{
  display: block;
  max-width: 100%;
  max-height: 420px;
  margin: 0 auto;
  object-fit: contain;
  background: #fff;
}}
.image-meta {{
  padding: 8px 10px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 10px;
  font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
  white-space: pre-wrap;
  word-break: break-word;
}}
.inline-code {{
  display: inline-block;
  padding: 0.08em 0.42em;
  border-radius: 6px;
  border: 1px solid var(--inline-code-line);
  background: var(--inline-code-bg);
  color: var(--inline-code-text);
  font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
  font-size: 0.95em;
  white-space: break-spaces;
}}
.code-shell {{
  margin: 10px 0 12px;
  border: 1px solid var(--code-line);
  border-radius: 12px;
  overflow: hidden;
  background: var(--code-bg);
  color: var(--code-text);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
}}
.code-label {{
  padding: 6px 10px;
  border-bottom: 1px solid var(--code-line);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #a9bdd6;
  background: rgba(8, 12, 18, 0.22);
  font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
}}
.codehilite {{
  margin: 0;
  padding: 12px 14px;
  background: transparent;
  color: var(--code-text);
  overflow-x: auto;
  font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
  font-size: 11px;
  line-height: 1.5;
}}
.codehilite, .codehilite * {{
  text-decoration: none !important;
}}
.codehilite pre {{
  margin: 0;
  color: inherit;
  background: transparent;
  white-space: pre-wrap;
  word-break: break-word;
}}
.codehilite .hll {{ background-color: #2a3448; }}
.codehilite .err {{ color: #ffb4b4; background-color: transparent; }}
.codehilite .w {{ color: #e6edf3; }}
.codehilite .x {{ color: #e6edf3; }}
.codehilite .nn,
.codehilite .nt,
.codehilite .nc,
.codehilite .nf,
.codehilite .fm {{
  text-decoration: none;
}}
pre.raw-block {{
  margin: 8px 0 0;
  padding: 10px 12px;
  background: rgba(255,255,255,0.85);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
  font-size: 11px;
}}
.footer-note {{
  margin-top: 18px;
  color: var(--muted);
  font-size: 10px;
  text-align: center;
}}
.empty {{
  color: var(--muted);
  font-style: italic;
}}
@media print {{
  .entry-collapsible .collapse-content {{
    max-height: none !important;
    overflow: visible !important;
  }}
  .entry-collapsible .collapse-content::after {{
    display: none !important;
  }}
  .collapse-toggle {{
    display: none !important;
  }}
}}
{CODE_STYLE}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a Codex CLI session JSONL file into an HTML or PDF transcript."
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="Path to a session JSONL file. Defaults to the latest file under ~/.codex/sessions.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output path. Defaults next to the input file with a .html extension, or .pdf with --pdf.",
    )
    parser.add_argument(
        "--chrome-path",
        default=os.environ.get("CHROME_BIN", "google-chrome"),
        help="Chrome/Chromium executable to use for HTML-to-PDF rendering.",
    )
    parser.add_argument(
        "--title",
        help="Display title in the PDF/HTML header. Defaults to the input filename.",
    )
    parser.add_argument(
        "--tags",
        help="Comma-separated tags to show in the header metadata (for example: auth, backend, prd).",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Write PDF instead of HTML.",
    )
    parser.add_argument(
        "--plaintext",
        action="store_true",
        help="Disable text rendering/styling for USER and ASSISTANT messages.",
    )
    parser.add_argument(
        "--keep-html",
        help="Write the intermediate HTML to this path before generating the PDF.",
    )
    parser.add_argument(
        "--collapse-threshold",
        type=int,
        default=DEFAULT_COLLAPSE_LINE_THRESHOLD,
        help="Collapse USER and ASSISTANT messages longer than this many text lines. Default: 15.",
    )
    parser.add_argument(
        "--collapse-lines",
        type=int,
        default=DEFAULT_COLLAPSED_VISIBLE_LINES,
        help="When collapsed, show this many lines. If larger than the threshold, it is clamped to the threshold. Default: 8.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Include developer messages, tool calls, tool outputs, and other non-essential records.",
    )
    parser.add_argument(
        "--include-turn-context",
        action="store_true",
        help="Include turn context entries. Only applies with --full.",
    )
    parser.add_argument(
        "--include-events",
        action="store_true",
        help="Include low-level event messages. Only applies with --full.",
    )
    return parser.parse_args()


def find_latest_session() -> Path:
    root = Path.home() / ".codex" / "sessions"
    files = sorted(root.glob("**/*.jsonl"), key=lambda path: path.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No session files found under {root}")
    return files[-1]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc
    return records


def iso_to_local(value: str | None) -> str:
    dt = parse_iso_datetime(value)
    if dt is None:
        return value or ""
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def first_and_last_timestamps(
    records: list[dict[str, Any]], meta: dict[str, Any]
) -> tuple[datetime | None, datetime | None]:
    timestamps = [
        record.get("timestamp", "") for record in records if record.get("timestamp")
    ]
    start = meta.get("timestamp") or (timestamps[0] if timestamps else "")
    end = timestamps[-1] if timestamps else start
    return parse_iso_datetime(start), parse_iso_datetime(end)


def format_header_date(start_time: datetime | None, end_time: datetime | None) -> str:
    dt = start_time or end_time
    if dt is None:
        return ""
    return dt.strftime("%b %d, %Y")


def format_duration(start_time: datetime | None, end_time: datetime | None) -> str:
    if start_time is None or end_time is None:
        return ""
    total_seconds = max((end_time - start_time).total_seconds(), 0)
    total_minutes = int((total_seconds + 59) // 60)
    days, remaining_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remaining_minutes, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def parse_tags(raw_tags: str | None) -> list[str]:
    if not raw_tags:
        return []
    tags: list[str] = []
    for item in raw_tags.split(","):
        tag = item.strip().lstrip("#").strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def sanitize_output_stem(title: str, fallback: str) -> str:
    normalized = re.sub(r"\s+", " ", title).strip()
    if not normalized:
        normalized = fallback
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", normalized)
    sanitized = re.sub(r"\s*-\s*", " - ", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip(" .-")
    sanitized = re.sub(r"( - ){2,}", " - ", sanitized)
    return sanitized or fallback


def normalize_collapse_settings(
    threshold: int, visible_lines: int
) -> tuple[int, int]:
    normalized_threshold = max(threshold, 1)
    normalized_visible_lines = max(visible_lines, 1)
    if normalized_visible_lines > normalized_threshold:
        normalized_visible_lines = normalized_threshold
    return normalized_threshold, normalized_visible_lines


def load_favicon_href() -> str:
    if not FAVICON_PATH.exists():
        return ""
    encoded = base64.b64encode(FAVICON_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def looks_like_file_name(name: str) -> bool:
    if name in {"", ".", ".."}:
        return False
    if name.startswith(".") and len(name) > 1:
        return True
    return "." in name


def format_file_link_display(target: str) -> str | None:
    if "://" in target:
        return None

    core_with_query, _, fragment = target.partition("#")
    core, _, _query = core_with_query.partition("?")
    file_part = core.rsplit("/", 1)[-1]
    if not looks_like_file_name(file_part):
        return None

    line_number = ""
    fragment_match = re.fullmatch(r"L(\d+)(?:C\d+)?", fragment)
    if fragment_match:
        line_number = fragment_match.group(1)

    colon_match = re.fullmatch(r"(.+):(\d+)(?::\d+)?", file_part)
    if colon_match and looks_like_file_name(colon_match.group(1)):
        file_part = colon_match.group(1)
        if not line_number:
            line_number = colon_match.group(2)

    return f"{file_part}:{line_number}" if line_number else file_part


def render_markdown_link(label: str, target: str) -> str:
    display = format_file_link_display(target) or label
    classes = ["message-link"]
    if format_file_link_display(target):
        classes.append("file-link")
    safe_display = html.escape(display)
    class_attr = " ".join(classes)
    return f'<span class="{class_attr}">{safe_display}</span>'


def count_text_lines(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines()) or 1


def count_message_lines(content: Iterable[dict[str, Any]]) -> int:
    total = 0
    for item in content:
        if item.get("type") in {"input_text", "output_text"}:
            total += count_text_lines(item.get("text", ""))
    return total


def pretty_json(value: Any) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ""
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return value
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    return json.dumps(value, indent=2, ensure_ascii=False)


def build_preview_entries(records: list[dict[str, Any]]) -> list[PreviewEntry]:
    entries: list[PreviewEntry] = []
    pending_user: PreviewEntry | None = None

    def flush_pending_user() -> None:
        nonlocal pending_user
        if pending_user is not None:
            entries.append(pending_user)
            pending_user = None

    for record in records:
        if record.get("type") != "response_item":
            continue
        payload = record.get("payload", {})
        if payload.get("type") != "message":
            continue
        role = payload.get("role", "")
        if role not in {"user", "assistant"}:
            continue

        parts: list[str] = []
        for item in payload.get("content", []):
            item_type = item.get("type", "unknown")
            if item_type in {"input_text", "output_text"}:
                text = item.get("text", "").strip()
                if text:
                    parts.append(text)
                continue
            if item_type in {"image_url", "input_image"}:
                parts.append("[image]")
                continue
            parts.append(f"[{item_type}] {pretty_json(item)}")

        body = "\n\n".join(part for part in parts if part).strip()
        if not body:
            body = "(empty)"
        entry = PreviewEntry(
            role=role,
            timestamp=iso_to_local(record.get("timestamp", "")),
            body=body,
        )
        if role == "user":
            pending_user = entry
        else:
            flush_pending_user()
            entries.append(entry)
    flush_pending_user()
    return entries


def protect_inline_tokens(text: str) -> tuple[str, list[str]]:
    replacements: list[str] = []

    def code_replacer(match: re.Match[str]) -> str:
        replacements.append(
            f'<span class="inline-code">{html.escape(match.group(1))}</span>'
        )
        return f"\x00TOKEN{len(replacements) - 1}\x00"

    text = INLINE_CODE_RE.sub(code_replacer, text)

    def link_replacer(match: re.Match[str]) -> str:
        replacements.append(render_markdown_link(match.group(1), match.group(2)))
        return f"\x00TOKEN{len(replacements) - 1}\x00"

    text = MARKDOWN_LINK_RE.sub(link_replacer, text)
    return text, replacements


def restore_inline_tokens(text: str, replacements: list[str]) -> str:
    def replacer(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return replacements[index]

    return INLINE_TOKEN_RE.sub(replacer, text)


def render_inline_text(text: str) -> str:
    protected, replacements = protect_inline_tokens(text)
    rendered = html.escape(protected)
    return restore_inline_tokens(rendered, replacements)


def render_text_block(text: str) -> str:
    cleaned = text.strip("\n")
    if not cleaned:
        return ""
    return f'<p class="message-text">{render_inline_text(cleaned)}</p>'


def render_plaintext_block(text: str) -> str:
    cleaned = text.strip("\n")
    if not cleaned:
        return ""
    return f'<p class="message-text">{html.escape(cleaned)}</p>'


def render_inline_markdown(text: str) -> str:
    protected, replacements = protect_inline_tokens(text)
    rendered = html.escape(protected)
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", rendered)
    rendered = re.sub(r"(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)", r"<em>\1</em>", rendered)
    return restore_inline_tokens(rendered, replacements)


def render_markdown_block(block: str) -> str:
    stripped = block.strip()
    if not stripped:
        return ""

    heading_match = re.match(r"^(#{1,3})\s+(.*)$", stripped)
    if heading_match:
        level = len(heading_match.group(1))
        text = render_inline_markdown(heading_match.group(2))
        return f'<div class="message-heading h{level}">{text}</div>'

    lines = [line.rstrip() for line in stripped.splitlines()]
    if all(re.match(r"^[-*]\s+", line) for line in lines if line.strip()):
        items = []
        for line in lines:
            if not line.strip():
                continue
            item = re.sub(r"^[-*]\s+", "", line)
            items.append(f"<li>{render_inline_markdown(item)}</li>")
        return f'<ul class="message-list">{"".join(items)}</ul>'

    if all(re.match(r"^\d+\.\s+", line) for line in lines if line.strip()):
        items = []
        for line in lines:
            if not line.strip():
                continue
            item = re.sub(r"^\d+\.\s+", "", line)
            items.append(f"<li>{render_inline_markdown(item)}</li>")
        return f'<ol class="message-list">{"".join(items)}</ol>'

    merged = "\n".join(lines)
    return f'<p class="message-text">{render_inline_markdown(merged)}</p>'


def highlight_code(code: str, language: str) -> str:
    lexer = TextLexer(stripall=False)
    normalized = language.strip().lower()
    if normalized:
        try:
            lexer = get_lexer_by_name(normalized, stripall=False)
        except ClassNotFound:
            lexer = TextLexer(stripall=False)
    highlighted = highlight(code.rstrip("\n"), lexer, CODE_FORMATTER)
    label = normalized or "text"
    return (
        '<div class="code-shell">'
        f'<div class="code-label">{html.escape(label)}</div>'
        f"{highlighted}"
        "</div>"
    )


def render_message_html(text: str) -> str:
    if not text.strip():
        return '<span class="empty">(empty)</span>'

    parts: list[str] = []
    last_end = 0
    for match in FENCED_BLOCK_RE.finditer(text):
        plain = text[last_end : match.start()]
        if plain.strip():
            for block in re.split(r"\n\s*\n", plain):
                rendered = render_markdown_block(block)
                if rendered:
                    parts.append(rendered)
        language = match.group(1)
        code = match.group(2)
        parts.append(highlight_code(code, language))
        last_end = match.end()

    tail = text[last_end:]
    if tail.strip():
        for block in re.split(r"\n\s*\n", tail):
            rendered = render_markdown_block(block)
            if rendered:
                parts.append(rendered)

    return "\n".join(parts) if parts else '<span class="empty">(empty)</span>'


def render_plain_message_html(text: str) -> str:
    if not text.strip():
        return '<span class="empty">(empty)</span>'

    parts: list[str] = []
    last_end = 0
    for match in FENCED_BLOCK_RE.finditer(text):
        plain = text[last_end : match.start()]
        if plain.strip():
            for block in re.split(r"\n\s*\n", plain):
                rendered = render_text_block(block)
                if rendered:
                    parts.append(rendered)
        language = match.group(1)
        code = match.group(2)
        parts.append(highlight_code(code, language))
        last_end = match.end()

    tail = text[last_end:]
    if tail.strip():
        for block in re.split(r"\n\s*\n", tail):
            rendered = render_text_block(block)
            if rendered:
                parts.append(rendered)

    return "\n".join(parts) if parts else '<span class="empty">(empty)</span>'


def render_plaintext_message_html(text: str) -> str:
    if not text.strip():
        return '<span class="empty">(empty)</span>'
    return render_plaintext_block(text)


def render_image_item(item: dict[str, Any]) -> str:
    image_url = item.get("image_url", "")
    label = item.get("name") or item.get("mime_type") or item.get("type", "image")
    meta_parts: list[str] = []
    if item.get("detail"):
        meta_parts.append(f"detail: {item['detail']}")
    if isinstance(image_url, str) and image_url.startswith("data:"):
        header = image_url.split(",", 1)[0]
        meta_parts.append(header)
    elif image_url:
        meta_parts.append(image_url)
    meta_html = ""
    if meta_parts:
        meta_html = (
            f'<div class="image-meta">{html.escape(" | ".join(meta_parts))}</div>'
        )
    if not image_url:
        return render_pre_entry("tool", "Image", "", pretty_json(item))
    return (
        '<div class="image-card">'
        f'<div class="image-label">{html.escape(label)}</div>'
        f'<img src="{html.escape(image_url)}" alt="{html.escape(label)}">'
        f"{meta_html}"
        "</div>"
    )


def render_message_items(items: Iterable[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in items:
        item_type = item.get("type", "unknown")
        if item_type in {"input_text", "output_text"}:
            rendered = render_message_html(item.get("text", ""))
            if rendered:
                parts.append(rendered)
            continue
        if item_type in {"image_url", "input_image"}:
            parts.append(render_image_item(item))
            continue
        parts.append(
            f'<pre class="raw-block">{html.escape(f"[{item_type}] {pretty_json(item)}")}</pre>'
        )
    return "\n".join(parts) if parts else '<span class="empty">(empty)</span>'


def render_message_payload(
    role: str,
    content: Iterable[dict[str, Any]],
    plaintext: bool = False,
) -> str:
    parts: list[str] = []
    for item in content:
        item_type = item.get("type", "unknown")
        if item_type in {"input_text", "output_text"}:
            text = item.get("text", "")
            if plaintext and role in {"user", "assistant"}:
                rendered = render_plaintext_message_html(text)
            else:
                rendered = (
                    render_plain_message_html(text)
                    if role == "user"
                    else render_message_html(text)
                )
            if rendered:
                parts.append(rendered)
            continue
        if item_type in {"image_url", "input_image"}:
            parts.append(render_image_item(item))
            continue
        parts.append(
            f'<pre class="raw-block">{html.escape(f"[{item_type}] {pretty_json(item)}")}</pre>'
        )
    return "\n".join(parts) if parts else '<span class="empty">(empty)</span>'


def should_keep_together(body_html: str) -> bool:
    plain = re.sub(r"<[^>]+>", "", body_html)
    compact_text = " ".join(plain.split())
    if len(compact_text) <= 900 and body_html.count("<img ") == 0:
        return True
    return False


def render_entry(
    kind: str,
    label: str,
    timestamp: str,
    body_html: str,
    collapsible: bool = False,
    collapse_lines: int = DEFAULT_COLLAPSED_VISIBLE_LINES,
) -> str:
    content = body_html if body_html else '<span class="empty">(empty)</span>'
    extra_class = " keep-together" if should_keep_together(content) else ""
    style_attr = ""
    if collapsible:
        extra_class += " entry-collapsible is-collapsed"
        style_attr = f' style="--collapsed-lines: {collapse_lines};"'
        content = (
            '<div class="collapse-content">'
            f"{content}"
            "</div>"
            '<button type="button" class="collapse-toggle" aria-expanded="false">Show more</button>'
        )
    return (
        f'<section class="entry {html.escape(kind)}{extra_class}"{style_attr}>'
        f'<div class="meta"><span class="label">{html.escape(label)}</span>'
        f"<span>{html.escape(iso_to_local(timestamp))}</span></div>"
        f'<div class="body">{content}</div>'
        f"</section>"
    )


def render_pre_entry(
    kind: str,
    label: str,
    timestamp: str,
    body: str,
) -> str:
    safe_body = html.escape(body) if body else "(empty)"
    return (
        f'<section class="entry {html.escape(kind)}">'
        f'<div class="meta"><span class="label">{html.escape(label)}</span>'
        f"<span>{html.escape(iso_to_local(timestamp))}</span></div>"
        f'<pre class="raw-block">{safe_body}</pre>'
        f"</section>"
    )


def build_transcript(
    records: list[dict[str, Any]],
    full: bool,
    include_turn_context: bool,
    include_events: bool,
    plaintext: bool,
    collapse_threshold: int,
    collapse_lines: int,
) -> tuple[dict[str, Any], list[str]]:
    meta: dict[str, Any] = {}
    sections: list[str] = []
    pending_user: str | None = None

    def flush_pending_user() -> None:
        nonlocal pending_user
        if pending_user is not None:
            sections.append(pending_user)
            pending_user = None

    for record in records:
        record_type = record.get("type")
        payload = record.get("payload", {})
        timestamp = record.get("timestamp", "")

        if record_type == "session_meta":
            meta = payload
            continue

        if not full:
            if record_type != "response_item":
                continue
            if payload.get("type") != "message":
                continue
            role = payload.get("role", "unknown")
            if role not in {"user", "assistant"}:
                continue
            content = payload.get("content", [])
            rendered_entry = render_entry(
                role,
                role.title(),
                timestamp,
                render_message_payload(role, content, plaintext),
                collapsible=count_message_lines(content) > collapse_threshold,
                collapse_lines=collapse_lines,
            )
            if role == "user":
                pending_user = rendered_entry
            else:
                flush_pending_user()
                sections.append(rendered_entry)
            continue

        if record_type == "turn_context":
            if include_turn_context:
                flush_pending_user()
                sections.append(
                    render_pre_entry(
                        "system",
                        "Turn Context",
                        timestamp,
                        pretty_json(payload),
                    )
                )
            continue

        if record_type == "event_msg":
            if include_events:
                flush_pending_user()
                event_label = f"Event: {payload.get('type', 'unknown')}"
                sections.append(
                    render_pre_entry(
                        "system",
                        event_label,
                        timestamp,
                        pretty_json(payload),
                    )
                )
            continue

        if record_type != "response_item":
            flush_pending_user()
            sections.append(
                render_pre_entry(
                    "system",
                    record_type or "unknown",
                    timestamp,
                    pretty_json(payload),
                )
            )
            continue

        payload_type = payload.get("type")

        if payload_type == "message":
            role = payload.get("role", "unknown")
            content = payload.get("content", [])
            rendered_entry = render_entry(
                role,
                role.title(),
                timestamp,
                render_message_payload(role, content, plaintext),
                collapsible=(
                    role in {"user", "assistant"}
                    and count_message_lines(content) > collapse_threshold
                ),
                collapse_lines=collapse_lines,
            )
            if role == "user":
                pending_user = rendered_entry
            else:
                flush_pending_user()
                sections.append(rendered_entry)
            continue

        flush_pending_user()
        if payload_type == "reasoning":
            summary = payload.get("summary") or []
            if summary:
                body = "\n".join(
                    item.get("text", pretty_json(item))
                    if isinstance(item, dict)
                    else str(item)
                    for item in summary
                )
            else:
                body = "Reasoning content is encrypted or omitted in the session log."
            sections.append(
                render_entry(
                    "reasoning",
                    "Reasoning",
                    timestamp,
                    render_text_block(body),
                )
            )
            continue

        if payload_type in {"function_call", "custom_tool_call"}:
            name = payload.get("name", payload_type)
            arguments = (
                payload.get("arguments")
                if payload_type == "function_call"
                else payload.get("input")
            )
            header = f"Tool Call: {name}"
            sections.append(
                render_pre_entry("tool", header, timestamp, pretty_json(arguments))
            )
            continue

        if payload_type in {"function_call_output", "custom_tool_call_output"}:
            call_id = payload.get("call_id", "")
            header = "Tool Output" + (f" ({call_id})" if call_id else "")
            sections.append(
                render_pre_entry("tool", header, timestamp, payload.get("output", ""))
            )
            continue

        if payload_type == "web_search_call":
            action = payload.get("action", {})
            query = (
                action.get("query")
                or ", ".join(action.get("queries", []))
                or "(no query)"
            )
            sections.append(
                render_entry("tool", "Web Search", timestamp, render_text_block(query))
            )
            continue

        sections.append(
            render_pre_entry(
                "system",
                payload_type or "response_item",
                timestamp,
                pretty_json(payload),
            )
        )

    flush_pending_user()
    return meta, sections


def build_html(
    title_text: str,
    meta: dict[str, Any],
    sections: list[str],
    full: bool,
    start_time: datetime | None,
    end_time: datetime | None,
    tags: list[str],
) -> str:
    _ = meta, full
    title = title_text
    favicon_href = load_favicon_href()
    body = (
        "\n".join(sections)
        if sections
        else '<p class="empty">No transcript entries found.</p>'
    )
    metadata_parts = [APP_LABEL]
    header_date = format_header_date(start_time, end_time)
    if header_date:
        metadata_parts.append(header_date)
    duration_text = format_duration(start_time, end_time)
    if duration_text:
        metadata_parts.append(duration_text)
    metadata_row = ""
    if metadata_parts:
        chips = "".join(
            f'<span class="chip">{html.escape(part)}</span>' for part in metadata_parts
        )
        metadata_row = f'<div class="summary">{chips}</div>'
    tags_row = ""
    if tags:
        tags_html = "".join(
            f'<span class="tag">#{html.escape(tag)}</span>' for tag in tags
        )
        tags_row = f'<div class="tags">{tags_html}</div>'
    favicon_link = ""
    if favicon_href:
        favicon_link = (
            f'\n  <link rel="icon" type="image/png" href="{html.escape(favicon_href)}">'
        )
    document = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{html.escape(HTML_TAB_TITLE)}</title>
  {favicon_link}
  <style>{STYLE}</style>
</head>
<body>
  <main>
    <header>
      <h1>{html.escape(title)}</h1>
      {metadata_row}
      {tags_row}
    </header>
    {body}
  </main>
</body>
</html>
"""
    return document.replace(
        "</body>",
        """  <script>
    document.addEventListener("click", (event) => {
      const button = event.target.closest(".collapse-toggle");
      if (!button) return;
      const entry = button.closest(".entry-collapsible");
      if (!entry) return;
      const isCollapsed = entry.classList.toggle("is-collapsed");
      button.textContent = isCollapsed ? "Show more" : "Show less";
      button.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
    });
  </script>
</body>""",
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def render_pdf(chrome_path: str, html_path: Path, pdf_path: Path) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        chrome_path,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        str(html_path),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Chrome executable not found: {chrome_path}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or exc.stdout.strip() or "unknown error"
        raise RuntimeError(f"Chrome PDF rendering failed: {stderr}") from exc
    if not pdf_path.exists():
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"Chrome did not produce the PDF file. {detail}")


def render_session(source_path: Path, options: RenderOptions) -> Path:
    source_path = source_path.expanduser().resolve()
    if options.keep_html and not options.pdf:
        raise ValueError("--keep-html only applies with --pdf.")

    collapse_threshold, collapse_lines = normalize_collapse_settings(
        options.collapse_threshold, options.collapse_lines
    )
    records = load_jsonl(source_path)
    display_title = options.title or source_path.name
    output_stem = sanitize_output_stem(display_title, source_path.stem)
    meta, sections = build_transcript(
        records,
        options.full,
        options.include_turn_context,
        options.include_events,
        options.plaintext,
        collapse_threshold,
        collapse_lines,
    )
    start_time, end_time = first_and_last_timestamps(records, meta)
    document = build_html(
        display_title,
        meta,
        sections,
        options.full,
        start_time,
        end_time,
        parse_tags(options.tags),
    )

    if options.pdf:
        output_path = (
            Path(options.output).expanduser().resolve()
            if options.output
            else (Path.cwd() / f"{output_stem}.pdf")
        )
        if options.keep_html:
            html_for_pdf = Path(options.keep_html).expanduser().resolve()
            write_text(html_for_pdf, document)
        else:
            with tempfile.TemporaryDirectory(prefix="codex-session-") as tmpdir:
                html_for_pdf = Path(tmpdir) / f"{output_stem}.html"
                write_text(html_for_pdf, document)
                render_pdf(options.chrome_path, html_for_pdf, output_path)
                return output_path

        render_pdf(options.chrome_path, html_for_pdf, output_path)
        return output_path

    html_path = (
        Path(options.output).expanduser().resolve()
        if options.output
        else (Path.cwd() / f"{output_stem}.html")
    )
    write_text(html_path, document)
    return html_path


def main() -> int:
    args = parse_args()
    try:
        source_path = Path(args.input).expanduser() if args.input else find_latest_session()
        output_path = render_session(
            source_path,
            RenderOptions(
                output=args.output,
                chrome_path=args.chrome_path,
                title=args.title,
                tags=args.tags,
                pdf=args.pdf,
                plaintext=args.plaintext,
                keep_html=args.keep_html,
                full=args.full,
                include_turn_context=args.include_turn_context,
                include_events=args.include_events,
                collapse_threshold=args.collapse_threshold,
                collapse_lines=args.collapse_lines,
            ),
        )
        print(output_path)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
