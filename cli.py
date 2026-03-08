#!/usr/bin/env python3
from __future__ import annotations

import curses
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from codex import (
    DEFAULT_COLLAPSE_LINE_THRESHOLD,
    DEFAULT_COLLAPSED_VISIBLE_LINES,
    PreviewEntry,
    RenderOptions,
    build_preview_entries,
    load_jsonl,
    render_session,
)


PROVIDER_OPTIONS = [
    ("codex", "Codex", Path.home() / ".codex" / "sessions", True),
    ("claude-code", "Claude Code", None, False),
    ("opencode", "OpenCode", None, False),
]


@dataclass(slots=True)
class ExplorerItem:
    label: str
    kind: str
    path: Path | None = None


class SessionBrowserApp:
    def __init__(self, stdscr: curses.window) -> None:
        self.stdscr = stdscr
        self.status_message = ""
        self.provider_index = 0
        self.current_provider = PROVIDER_OPTIONS[0]
        self.current_dir = PROVIDER_OPTIONS[0][2]

    def run(self) -> None:
        curses.curs_set(0)
        self.stdscr.keypad(True)
        curses.use_default_colors()
        self._init_colors()

        while True:
            provider = self.provider_menu()
            if provider is None:
                return
            key, _display_name, root, enabled = provider
            if not enabled or root is None:
                self.status_message = f"`{provider[1]}` is not implemented yet."
                continue
            if not root.exists():
                self.status_message = f"Missing sessions directory: {root}"
                continue

            self.current_provider = provider
            self.current_dir = root
            outcome = self.file_browser(root)
            if outcome == "quit":
                return

    def provider_menu(self) -> tuple[str, str, Path | None, bool] | None:
        selection = self.provider_index
        while True:
            self._clear()
            height, width = self.stdscr.getmaxyx()
            title = "Select provider"
            subtitle = "Use ↑/↓ to move, Enter to proceed, Esc to quit"
            self._draw_title(title, subtitle)

            start_row = 4
            for index, provider in enumerate(PROVIDER_OPTIONS):
                _key, name, _root, enabled = provider
                prefix = "› " if index == selection else "  "
                suffix = "" if enabled else " (coming soon)"
                attr = self._selected_attr() if index == selection else curses.color_pair(0)
                if not enabled and index != selection:
                    attr = curses.color_pair(4)
                line = f"{prefix}{name}{suffix}"
                self._addstr(start_row + index, 2, line[: width - 4], attr)

            self._draw_status(height - 2, width)
            key = self.stdscr.getch()
            if key in {27, ord("q")}:
                return None
            if key == curses.KEY_UP:
                selection = (selection - 1) % len(PROVIDER_OPTIONS)
            elif key == curses.KEY_DOWN:
                selection = (selection + 1) % len(PROVIDER_OPTIONS)
            elif key in {10, 13, curses.KEY_ENTER}:
                self.provider_index = selection
                return PROVIDER_OPTIONS[selection]

    def file_browser(self, root: Path) -> str:
        selected_index = self._first_selectable_index(
            self._list_explorer_items(root, self.current_dir)
        )
        while True:
            items = self._list_explorer_items(root, self.current_dir)
            if selected_index >= len(items) or not self._is_selectable(items[selected_index]):
                selected_index = self._first_selectable_index(items)

            self._clear()
            height, width = self.stdscr.getmaxyx()
            relative = "." if self.current_dir == root else str(self.current_dir.relative_to(root))
            self._draw_title(
                f"{self.current_provider[1]} sessions",
                f"{root} / {relative}",
            )

            visible_rows = max(1, height - 9)
            scroll = max(0, min(selected_index - visible_rows + 1, selected_index))
            start_row = 4
            for row_offset, item in enumerate(items[scroll : scroll + visible_rows]):
                absolute_index = scroll + row_offset
                attr = self._selected_attr() if absolute_index == selected_index else curses.color_pair(0)
                label = item.label
                if item.kind == "separator":
                    self._addstr(start_row + row_offset, 2, ""[: width - 4], curses.color_pair(0))
                    continue
                if item.kind == "dir":
                    label += "/"
                if item.kind in {"home", "back"} and absolute_index != selected_index:
                    attr = curses.color_pair(4)
                self._addstr(start_row + row_offset, 2, label[: width - 4], attr)

            detail_lines = self._browser_detail_lines(items[selected_index], width)
            detail_row = height - 5
            for offset, line in enumerate(detail_lines):
                self._addstr(detail_row + offset, 2, line[: width - 4], curses.color_pair(4))

            footer = "Enter: open  ←/Backspace: up  Home item: provider menu  Esc: quit"
            self._addstr(height - 3, 2, footer[: width - 4], curses.color_pair(4))
            self._draw_status(height - 2, width)

            key = self.stdscr.getch()
            if key in {27, ord("q")}:
                return "quit"
            if key == curses.KEY_UP:
                selected_index = self._move_selection(items, selected_index, -1)
                continue
            if key == curses.KEY_DOWN:
                selected_index = self._move_selection(items, selected_index, 1)
                continue
            if key in {curses.KEY_LEFT, curses.KEY_BACKSPACE, 127}:
                if self.current_dir != root:
                    self.current_dir = self.current_dir.parent
                    selected_index = self._first_selectable_index(
                        self._list_explorer_items(root, self.current_dir)
                    )
                continue
            if key not in {10, 13, curses.KEY_ENTER}:
                continue

            chosen = items[selected_index]
            if chosen.kind == "home":
                self.status_message = ""
                return "home"
            if chosen.kind == "back":
                if self.current_dir != root:
                    self.current_dir = self.current_dir.parent
                    selected_index = self._first_selectable_index(
                        self._list_explorer_items(root, self.current_dir)
                    )
                continue
            if chosen.kind == "dir" and chosen.path is not None:
                self.current_dir = chosen.path
                selected_index = self._first_selectable_index(
                    self._list_explorer_items(root, self.current_dir)
                )
                continue
            if chosen.kind == "file" and chosen.path is not None:
                if self.preview_file(chosen.path):
                    options = self.configure_render(chosen.path)
                    if options is None:
                        continue
                    try:
                        output_path = render_session(chosen.path, options)
                    except Exception as exc:
                        self.status_message = f"Error: {exc}"
                    else:
                        self.status_message = f"Generated: {output_path}"

    def preview_file(self, path: Path) -> bool:
        entries = build_preview_entries(load_jsonl(path))
        cached_width = 0
        cached_lines: list[tuple[str, int]] = []
        scroll = 0

        while True:
            self._clear()
            height, width = self.stdscr.getmaxyx()
            if width != cached_width:
                cached_lines = self._build_preview_lines(entries, max(20, width - 4))
                cached_width = width
                scroll = min(scroll, max(0, len(cached_lines) - 1))

            self._draw_title(path.name, "Preview · Esc to go back · Enter to configure")
            visible_rows = max(1, height - 7)
            max_scroll = max(0, len(cached_lines) - visible_rows)
            scroll = max(0, min(scroll, max_scroll))

            for row_offset, (line, color_pair) in enumerate(cached_lines[scroll : scroll + visible_rows]):
                self._addstr(4 + row_offset, 2, line[: width - 4], curses.color_pair(color_pair))

            self._addstr(
                height - 3,
                2,
                "↑/↓/PgUp/PgDn to scroll",
                curses.color_pair(4),
            )
            self._draw_status(height - 2, width)

            key = self.stdscr.getch()
            if key == 27:
                return False
            if key in {10, 13, curses.KEY_ENTER}:
                return True
            if key == curses.KEY_UP:
                scroll = max(0, scroll - 1)
            elif key == curses.KEY_DOWN:
                scroll = min(max_scroll, scroll + 1)
            elif key == curses.KEY_PPAGE:
                scroll = max(0, scroll - visible_rows)
            elif key == curses.KEY_NPAGE:
                scroll = min(max_scroll, scroll + visible_rows)

    def configure_render(self, path: Path) -> RenderOptions | None:
        config = {
            "pdf": False,
            "title": "",
            "tags": "",
            "plaintext": False,
            "full": False,
            "include_turn_context": False,
            "include_events": False,
            "collapse_threshold": DEFAULT_COLLAPSE_LINE_THRESHOLD,
            "collapse_lines": DEFAULT_COLLAPSED_VISIBLE_LINES,
        }
        selected_index = 2

        while True:
            items = [
                ("Cancel", "", "action-cancel"),
                ("Generate", "", "action-generate"),
                ("Output", "PDF" if config["pdf"] else "HTML", "toggle"),
                ("Title", config["title"] or f"(default: {path.name})", "text"),
                ("Tags", config["tags"] or "(none)", "text"),
                ("Plaintext", "On" if config["plaintext"] else "Off", "toggle"),
                ("Full", "On" if config["full"] else "Off", "toggle"),
                (
                    "Turn Context",
                    "On" if config["include_turn_context"] else "Off",
                    "toggle",
                ),
                ("Events", "On" if config["include_events"] else "Off", "toggle"),
                ("Collapse Threshold", str(config["collapse_threshold"]), "number"),
                ("Collapse Lines", str(config["collapse_lines"]), "number"),
            ]

            self._clear()
            height, width = self.stdscr.getmaxyx()
            self._draw_title(path.name, "Configure export · Enter to edit/toggle · Esc to cancel")
            for index, (label, value, _kind) in enumerate(items):
                attr = self._config_item_attr(index, selected_index, label)
                line = f"{label:<18} {value}".rstrip()
                row = 4 + index + (1 if index >= 2 else 0)
                self._addstr(row, 2, line[: width - 4], attr)

            self._draw_status(height - 2, width)
            key = self.stdscr.getch()
            if key == 27:
                return None
            if key == curses.KEY_UP:
                selected_index = (selected_index - 1) % len(items)
                continue
            if key == curses.KEY_DOWN:
                selected_index = (selected_index + 1) % len(items)
                continue
            if key not in {10, 13, curses.KEY_ENTER, ord(" ")}:
                continue

            label, _value, kind = items[selected_index]
            if kind == "toggle":
                key_name = self._config_key_for_label(label)
                if key_name is not None:
                    config[key_name] = not config[key_name]
                continue
            if kind == "text":
                key_name = self._config_key_for_label(label)
                if key_name is None:
                    continue
                initial = str(config[key_name])
                updated = self.prompt_input(f"{label}:", initial)
                if updated is not None:
                    config[key_name] = updated.strip()
                continue
            if kind == "number":
                key_name = self._config_key_for_label(label)
                if key_name is None:
                    continue
                updated = self.prompt_input(f"{label}:", str(config[key_name]))
                if updated is None:
                    continue
                try:
                    config[key_name] = max(1, int(updated))
                except ValueError:
                    self.status_message = f"{label} must be a positive integer."
                continue
            if kind == "action-cancel":
                return None
            if kind == "action-generate":
                return RenderOptions(
                    title=(config["title"] or None),
                    tags=(config["tags"] or None),
                    pdf=bool(config["pdf"]),
                    plaintext=bool(config["plaintext"]),
                    full=bool(config["full"]),
                    include_turn_context=bool(config["include_turn_context"]),
                    include_events=bool(config["include_events"]),
                    collapse_threshold=int(config["collapse_threshold"]),
                    collapse_lines=int(config["collapse_lines"]),
                )

    def prompt_input(self, prompt: str, initial: str = "") -> str | None:
        value = initial
        curses.curs_set(1)
        while True:
            height, width = self.stdscr.getmaxyx()
            self._addstr(height - 2, 2, " " * max(1, width - 4), curses.color_pair(0))
            prompt_text = f"{prompt} {value}"
            self._addstr(height - 2, 2, prompt_text[: width - 4], self._selected_attr())
            self.stdscr.move(height - 2, min(width - 3, len(prompt) + len(value) + 3))
            key = self.stdscr.get_wch()
            if key == "\x1b":
                curses.curs_set(0)
                return None
            if key in {"\n", "\r"}:
                curses.curs_set(0)
                return value
            if key in {"\x7f", "\b"} or key == curses.KEY_BACKSPACE:
                value = value[:-1]
                continue
            if isinstance(key, str) and key.isprintable():
                value += key

    def _build_preview_lines(
        self, entries: list[PreviewEntry], width: int
    ) -> list[tuple[str, int]]:
        lines: list[tuple[str, int]] = []
        for entry in entries:
            color_pair = 2 if entry.role == "user" else 3
            header = f"{entry.role.upper()}  {entry.timestamp}".strip()
            lines.append((header, color_pair))
            for paragraph in entry.body.splitlines() or [""]:
                wrapped = textwrap.wrap(
                    paragraph,
                    width=max(8, width),
                    replace_whitespace=False,
                    drop_whitespace=False,
                ) or [""]
                lines.extend((segment, color_pair) for segment in wrapped)
            lines.append(("", color_pair))
        return lines or [("(empty)", 4)]

    def _list_explorer_items(self, root: Path, current_dir: Path) -> list[ExplorerItem]:
        items: list[ExplorerItem] = [ExplorerItem("Home", "home")]
        if current_dir != root:
            items.append(ExplorerItem("Back", "back", current_dir.parent))
        items.append(ExplorerItem("", "separator"))

        directories = sorted(
            [path for path in current_dir.iterdir() if path.is_dir()],
            key=lambda path: path.name,
            reverse=True,
        )
        files = sorted(
            [
                path
                for path in current_dir.iterdir()
                if path.is_file() and path.suffix == ".jsonl"
            ],
            key=lambda path: path.name,
            reverse=True,
        )
        items.extend(ExplorerItem(path.name, "dir", path) for path in directories)
        items.extend(ExplorerItem(path.name, "file", path) for path in files)
        return items

    def _is_selectable(self, item: ExplorerItem) -> bool:
        return item.kind != "separator"

    def _first_selectable_index(self, items: list[ExplorerItem]) -> int:
        for index, item in enumerate(items):
            if item.kind in {"dir", "file"}:
                return index
        for index, item in enumerate(items):
            if self._is_selectable(item):
                return index
        return 0

    def _move_selection(
        self, items: list[ExplorerItem], selected_index: int, direction: int
    ) -> int:
        if not items:
            return 0
        next_index = selected_index
        for _ in range(len(items)):
            next_index = (next_index + direction) % len(items)
            if self._is_selectable(items[next_index]):
                return next_index
        return selected_index

    def _browser_detail_lines(self, item: ExplorerItem, width: int) -> list[str]:
        if item.kind == "file" and item.path is not None:
            stat = item.path.stat()
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %Y %H:%M")
            size = self._format_size(stat.st_size)
            return [
                f"Selected: {item.path.name}",
                f"Modified: {modified}    Size: {size}",
            ]
        if item.kind == "dir" and item.path is not None:
            return [f"Directory: {item.path.name}/", "Press Enter to open"]
        if item.kind == "home":
            return ["Home", "Return to provider selection"]
        if item.kind == "back":
            return ["Back", "Go up one directory"]
        return ["", ""]

    def _format_size(self, size_bytes: int) -> str:
        units = ["B", "KB", "MB", "GB"]
        size = float(size_bytes)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(size)} {unit}"
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size_bytes} B"

    def _config_key_for_label(self, label: str) -> str | None:
        mapping = {
            "Output": "pdf",
            "Title": "title",
            "Tags": "tags",
            "Plaintext": "plaintext",
            "Full": "full",
            "Turn Context": "include_turn_context",
            "Events": "include_events",
            "Collapse Threshold": "collapse_threshold",
            "Collapse Lines": "collapse_lines",
        }
        return mapping.get(label)

    def _init_colors(self) -> None:
        curses.start_color()
        light_pink = 225 if getattr(curses, "COLORS", 0) >= 256 else curses.COLOR_MAGENTA
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(2, light_pink, -1)
        curses.init_pair(3, curses.COLOR_WHITE, -1)
        curses.init_pair(4, curses.COLOR_CYAN, -1)
        curses.init_pair(5, curses.COLOR_RED, -1)
        curses.init_pair(6, curses.COLOR_GREEN, -1)

    def _selected_attr(self) -> int:
        return curses.color_pair(1) | curses.A_BOLD

    def _config_item_attr(self, index: int, selected_index: int, label: str) -> int:
        if index == selected_index:
            return self._selected_attr()
        if label == "Generate":
            return curses.color_pair(6) | curses.A_BOLD
        if label == "Cancel":
            return curses.color_pair(5)
        return curses.color_pair(0)

    def _draw_title(self, title: str, subtitle: str) -> None:
        height, width = self.stdscr.getmaxyx()
        self._addstr(1, 2, title[: width - 4], curses.A_BOLD)
        self._addstr(2, 2, subtitle[: width - 4], curses.color_pair(4))

    def _draw_status(self, row: int, width: int) -> None:
        if not self.status_message:
            return
        if self.status_message.startswith("Error"):
            color = curses.color_pair(5)
        elif self.status_message.startswith("Generated"):
            color = curses.color_pair(6)
        else:
            color = curses.color_pair(4)
        self._addstr(row, 2, self.status_message[: width - 4], color)

    def _addstr(self, y: int, x: int, text: str, attr: int = 0) -> None:
        height, width = self.stdscr.getmaxyx()
        if y < 0 or y >= height or x >= width:
            return
        safe_text = text[: max(0, width - x - 1)]
        try:
            self.stdscr.addstr(y, x, safe_text, attr)
        except curses.error:
            pass

    def _clear(self) -> None:
        self.stdscr.erase()


def main() -> int:
    def wrapped(stdscr: curses.window) -> None:
        app = SessionBrowserApp(stdscr)
        app.run()

    curses.wrapper(wrapped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
