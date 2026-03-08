# chathistory

`chathistory` is a local transcript browser and exporter for AI coding session logs. It is built for navigating session history, previewing conversations in the terminal, and exporting readable HTML or PDF archives you can keep or share.

Right now the project supports `Codex` session logs under `~/.codex/sessions/`. `Claude Code` and `OpenCode` are planned later.

## What it does

- Browse session files in a terminal UI
- Preview USER and ASSISTANT messages with lightweight formatting
- Export transcripts as styled HTML
- Export PDF through headless Chrome
- Add title, tags, and transcript detail controls at export time

## Requirements

- Python `>=3.13`
- `uv`
- `google-chrome` available locally for PDF export

Install dependencies:

```bash
uv sync
```

## Main app: `cli.py`

This is the main interface for the repository.

Launch it with:

```bash
uv run python cli.py
```

### Flow

1. Choose a provider (`Codex` works now)
2. Navigate inside `~/.codex/sessions/` with arrow keys
3. Open a `.jsonl` file to preview the conversation
4. Press `Enter` again to configure export options
5. Generate HTML or PDF, then return to the browser

### Controls

- `↑` / `↓` — move selection
- `Enter` — open folder, preview file, or confirm action
- `Esc` — go back / close preview / quit current screen
- `Backspace` or `←` — go up one directory
- `Home` entry — return to provider selection
- `PgUp` / `PgDn` — scroll preview faster

### Preview behavior

- Shows only USER and ASSISTANT messages
- Consecutive USER messages collapse to only the last one, matching the exported transcript flow
- USER text is tinted light pink; ASSISTANT text is white

## Direct renderer: `codex.py`

`codex.py` is the lower-level export tool. Think of it like `ffmpeg`: less guided, more direct, and good for scripting or one-shot conversions.

Run it with:

```bash
uv run python codex.py input.jsonl
```

If no input is given, it automatically picks the latest file under `~/.codex/sessions/`.

### Common examples

Generate HTML:

```bash
uv run python codex.py input.jsonl
```

Generate PDF:

```bash
uv run python codex.py input.jsonl --pdf
```

Set title and tags:

```bash
uv run python codex.py input.jsonl --title "Belajar Auth" --tags "auth, backend"
```

Include richer internal records:

```bash
uv run python codex.py input.jsonl --full --include-turn-context --include-events
```

### Flags

- `input` — path to a session `.jsonl`; defaults to the latest session
- `-o`, `--output` — output path; defaults to `./<session>.html` or `./<session>.pdf`
- `--chrome-path` — Chrome/Chromium binary used for PDF rendering; defaults to `google-chrome` or `CHROME_BIN`
- `--title` — custom document title shown in the transcript header
- `--tags` — comma-separated tags shown under the header metadata
- `--pdf` — write PDF instead of HTML
- `--plaintext` — disable markdown-like styling for USER and ASSISTANT text
- `--keep-html` — keep the intermediate HTML at the given path when exporting PDF
- `--collapse-threshold` — collapse USER/ASSISTANT entries longer than this many lines in HTML
- `--collapse-lines` — visible lines when collapsed; clamped so it never exceeds `--collapse-threshold`
- `--full` — include developer messages, tool calls, tool outputs, and other non-essential records
- `--include-turn-context` — include turn-context records when `--full` is enabled
- `--include-events` — include low-level event records when `--full` is enabled

## Output notes

- Browser tab title is fixed to `chathistory`
- Local file references like `[PRD.md](/path/to/PRD.md#L21)` render as non-clickable blue text like `PRD.md:21`
- HTML output supports collapsing long USER and ASSISTANT messages
- PDF output always renders fully expanded content
- Chrome's default PDF URL/date header is suppressed; page numbering remains

## Repository layout

- `cli.py` — terminal browser and export workflow
- `codex.py` — direct renderer and shared export logic
- `assets/` — static assets such as the browser-tab icon

