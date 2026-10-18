# Webaloo

**Webaloo** is a local-first, file-backed visual bookmark manager inspired by Symbaloo. It stores boards (**webmixes**) as plain directories and bookmarks (**tiles**) as individual, human-readable JSON files—making your bookmarks Git-versionable, trivially editable in VS Code, offline-capable, and completely decoupled from cloud providers.

---

## Key Features

- **Filesystem as Source of Truth:** Zero SQL/NoSQL databases. Every directory in `./webmixes/` is a webmix (`_mix.json`), and every `.json` file inside it is a tile.
- **Exact 2D Spatial Memory:** Fixed `cols × rows` grids preserve empty slots (`float: true` behavior—no unwanted auto-compacting). Drag a tile to an empty slot to move it, or drop it onto an occupied slot to **atomically swap** coordinates on disk.
- **4-Mode Offline-Ready Icon System:**
  1. **Auto-Fetched & Uploaded Icons (`cached`):** Automatically extracts page `<title>` and highest-resolution `apple-touch-icon` / favicon into `./webmixes/_icons/`, or accepts custom uploaded `.png`, `.svg`, `.ico`, `.webp`, and `.jpg` icons.
  2. **Lucide Vector Icons (`lucide`):** Built-in searchable picker of crisp vector icons.
  3. **External Image URL (`external`):** Direct image URL rendering.
  4. **Styled Monogram Badge (`monogram`):** Automatic 1–4 character badge fallback when offline or linking to internal LAN appliances.
- **Off-Grid & LAN Friendly:** Link directly to `http://localhost:...`, private subnet dashboards (`http://192.168.x.x:...`), and custom desktop URI schemes (`vscode://`, `obsidian://`).
- **Global Instant Search (`Ctrl+K` or `/`):** In-memory tokenized search across all webmixes by tile name, URL, `#tags`, and board title in `< 2ms`, with full keyboard navigation (`↑`/`↓`, `Enter` to open, `Alt+Enter` to jump to board & highlight tile).
- **Live External File Sync (SSE):** Watches `./webmixes/` via `watchfiles` and automatically refreshes the browser via Server-Sent Events when you edit JSON files in VS Code or run `git pull` (deferring reloads safely if a modal dialog is open).

---

## Quick Start (`uv`)

```powershell
# 1. Install dependencies into the local .venv via uv
uv sync

# 2. Start Webaloo on http://127.0.0.1:8080 (using ./webmixes)
uv run python -m webaloo

# Or use the installed script entrypoint with custom directory and port
uv run webaloo --dir C:/path/to/webmixes --port 8765
```

### Configuration & Environment Variables

| Option | CLI Argument | Environment Variable | Default |
| :--- | :--- | :--- | :--- |
| **Data Directory** | `--dir` | `WEBALOO_DIR` | `./webmixes` |
| **Bind Address** | `--host` | `WEBALOO_HOST` | `127.0.0.1` |
| **Bind Port** | `--port` | `WEBALOO_PORT` | `8080` |

*(CLI arguments take precedence over environment variables.)*

---

## Directory Layout

```text
./webmixes/
├── _icons/                         # Offline cache for fetched favicons & uploaded icons
├── default/
│   ├── _mix.json                   # Webmix metadata (title, order, grid_cols, grid_rows, theme, background)
│   ├── google.json                 # Tile payload (id = "google")
│   ├── tradingview.json
│   └── lemonade.json
├── trading/
│   ├── _mix.json
│   ├── es-futures.json
│   └── bookmap.json
└── audio-studio/
    ├── _mix.json
    └── kvr-audio.json
```

---

## Running Tests

```powershell
uv run pytest -v
```

---

## Documentation

- [**User & Operations Guide (`user_guide.md`)**](file:///C:/Dev/github/philippeback/webaloo/user_guide.md) — Complete operational manual, keyboard shortcuts, UI workflows, and VS Code / Git editing guide.
- [**Software Design & Implementation (`sdi.md`)**](file:///C:/Dev/github/philippeback/webaloo/sdi.md) — Architectural invariants, state machines, spatial algorithms, API contracts, and full EARS traceability matrix.
- [**Functional Specification (`WebalooSpec.md`)**](file:///C:/Dev/github/philippeback/webaloo/WebalooSpec.md) — Data model, UX mechanics, and HTTP endpoint overview.
- [**EARS Requirements (`WebalooEARS-Spec.md`)**](file:///C:/Dev/github/philippeback/webaloo/WebalooEARS-Spec.md) — Formal Easy Approach to Requirements Syntax specification (`REQ-FS`, `REQ-MIX`, `REQ-GRID`, `REQ-TILE`, `REQ-ICON`, `REQ-SRCH`, `REQ-SYNC`).
- [**Original Briefing (`Briefing.md`)**](file:///C:/Dev/github/philippeback/webaloo/Briefing.md) — Architectural concept and motivation.
