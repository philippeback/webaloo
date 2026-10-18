# Webaloo Specification

**Webaloo** is a local-first, file-backed visual bookmark manager inspired by Symbaloo. It stores boards (**webmixes**) as plain directories and bookmarks (**tiles**) as individual, human-readable JSON files—making all data Git-friendly, trivially editable in VS Code, offline-capable, and decoupled from cloud services.

---

## 1. Core Principles

- **Filesystem as Source of Truth:** No SQL/NoSQL database. Directories represent webmixes; `.json` files represent tiles.
- **Human-Friendly & Git-Versionable:** Filenames are slugified from tile names (e.g., `tradingview.json`), formatted with clean 2-space indentation, and self-contained alongside cached icons.
- **Exact 2D Spatial Memory:** Fixed `cols × rows` grids preserve empty slots (`float: true` behavior). Tiles stay exactly where placed and swap cleanly when dropped onto an occupied cell.
- **Zero-Friction Local Runtime:** Lightweight Python backend (FastAPI) with server-rendered HTMX + Tailwind CSS frontend and live reload on external disk changes.

---

## 2. Directory Layout & Data Model

By default, Webaloo reads and writes to `./webmixes` inside the working repository. This path can be overridden via the `WEBALOO_DIR` environment variable or the `--dir` CLI argument.

```text
./webmixes/
├── _icons/                         # Offline cache for fetched favicons & custom uploaded icons
│   ├── tradingview.png
│   ├── google.ico
│   └── custom_bookmap.svg
├── default/
│   ├── _mix.json                   # Webmix metadata (title, order, grid size, background)
│   ├── google.json                 # Tile payload (ID = filename stem "google")
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

### 2.1 Webmix Metadata Schema (`_mix.json`)

Located in each webmix folder (`./webmixes/{mix_slug}/_mix.json`):

```json
{
  "title": "Trading & Markets",
  "order": 1,
  "grid_cols": 12,
  "grid_rows": 8,
  "theme": "dark",
  "background": "#0f172a",
  "created_at": "2026-10-18T20:50:00Z"
}
```

- **`title`** *(string)*: Display name in the top tab bar.
- **`order`** *(integer)*: Sort order of the tab in the UI (`0, 1, 2...`).
- **`grid_cols` / `grid_rows`** *(integer)*: Fixed 2D grid dimensions (default `12 × 8`).
- **`theme`** *(string)*: `"dark"` or `"light"`.
- **`background`** *(string)*: CSS color, gradient, or local image reference for the board backdrop.
- **`created_at`** *(ISO-8601 string)*: Creation timestamp.

### 2.2 Tile JSON Schema (`{tile_slug}.json`)

Located inside a webmix folder (`./webmixes/{mix_slug}/{tile_slug}.json`).
- **Tile ID:** Derived directly from the filename stem (`tradingview.json` $\rightarrow$ `id = "tradingview"`). If an explicit `"id"` field is present in the JSON, it is kept synchronized with the filename stem.
- **Filename Generation:** When creating a tile from the UI, the tile's `name` is slugified (`"TradingView"` $\rightarrow$ `tradingview.json`). If a collision occurs in the same folder, a numeric suffix is appended (`tradingview-2.json`).

```json
{
  "name": "TradingView",
  "url": "https://www.tradingview.com/chart/",
  "x": 3,
  "y": 2,
  "w": 1,
  "h": 1,
  "bg_color": "#131722",
  "text_color": "#ffffff",
  "show_label": true,
  "icon_type": "cached",
  "icon": "lucide:candlestick-chart",
  "icon_url": "/icons/tradingview.png",
  "monogram": "TV",
  "tags": ["trading", "market"],
  "target": "_blank"
}
```

- **`name`** *(string)*: Display label on the tile and search index.
- **`url`** *(string)*: Destination URL. Supports `https://`, `http://` (including LAN/localhost addresses like `http://192.168.1.50:8888` or `http://localhost:8001`), and custom URI schemes.
- **`x`, `y`** *(integer)*: 0-indexed column (`0 <= x < grid_cols`) and row (`0 <= y < grid_rows`).
- **`w`, `h`** *(integer)*: Width and height in grid cells (default `1 × 1`).
- **`bg_color` / `text_color`** *(string)*: Tile background and label hex colors.
- **`show_label`** *(boolean)*: Whether to render the text label beneath the icon.
- **`icon_type`** *(string)*: `"cached"` (auto-fetched or uploaded image in `_icons/`), `"lucide"` (built-in vector icon), `"external"` (direct URL), or `"monogram"` (styled text initials).
- **`icon`** *(string | null)*: Lucide icon identifier (e.g., `"candlestick-chart"`).
- **`icon_url`** *(string | null)*: Path to cached icon in `/icons/...` or external URL.
- **`monogram`** *(string | null)*: 1–4 character badge text when using monogram style or as fallback.
- **`tags`** *(array of strings)*: Keywords for instant global filtering.
- **`target`** *(string)*: `"_blank"` (default, opens new tab) or `"_self"`.

---

## 3. Technology Stack

| Layer | Choice | Purpose |
| :--- | :--- | :--- |
| **Backend** | **Python 3.11+ & FastAPI** | Async HTTP endpoints, `pathlib` file operations, SSE live reload stream, and static asset serving. |
| **Templating** | **Jinja2 + HTMX** | Server-rendered HTML partials for fast tab switching, modals, and grid updates without a SPA build pipeline. |
| **Styling & Icons** | **Tailwind CSS + Lucide Icons** | Clean glassmorphism/dark UI, responsive tile scaling, and crisp vector icons. |
| **2D Grid Engine** | **CSS Grid + Sortable/Custom Drag-Swap or Gridstack.js (`float: true`)** | Fixed `cols × rows` coordinate grid with explicit empty slots and direct drag-to-move / drag-to-swap mechanics. |
| **Favicon Worker** | **httpx + BeautifulSoup4 / Pillow** | Discovers highest-resolution `apple-touch-icon`, manifest icon, or favicon and saves to `./webmixes/_icons/`. |
| **Live File Watcher** | **watchfiles** | Watches `./webmixes` for external changes (e.g., editing JSON in VS Code) and pushes an SSE reload event to the browser. |

---

## 4. User Experience & Core Mechanics

### 4.1 Symbaloo-Style Grid Interaction
- **Fixed Coordinate Slots:** Every cell `(x, y)` in the `grid_cols × grid_rows` matrix is rendered. Empty slots appear as subtle translucent cells that highlight on hover.
- **Left-Click Occupied Tile:** Immediately opens `tile.url` (respecting `tile.target`).
- **Left-Click Empty Slot:** Opens the **Create Tile** modal pre-populated with that slot's `(x, y)` coordinates.
- **Drag & Drop:**
  - Dragging a tile to an **empty cell** updates the tile's `(x, y)` in its `.json` file.
  - Dragging a tile onto an **occupied cell** **swaps** the `(x, y)` coordinates of both tiles atomically on disk.
- **Right-Click Context Menu (or Hover Edit Button):**
  - **Edit Tile:** Opens the tile editor modal.
  - **Duplicate Tile:** Clones the tile into the nearest empty cell.
  - **Move to Webmix:** Moves the `.json` file to another webmix folder (at the same `(x, y)` if free, or the first available empty cell).
  - **Delete Tile:** Removes the `.json` file from disk (with confirmation or undo toast).

### 4.2 Tile Editor & Icon System
When creating or editing a tile:
1. **URL Auto-Discovery:** Typing or pasting a URL triggers a debounced lookup (`POST /api/icons/fetch`) that fetches the page `<title>` (if `name` is still blank) and downloads the best available site icon into `./webmixes/_icons/`.
2. **Appearance Tabs:**
   - **Site Icon / Upload:** Use the auto-fetched icon, paste a custom image URL, or upload a custom image file to `_icons/`.
   - **Lucide Icon Picker:** Searchable grid of built-in vector icons.
   - **Monogram Badge:** Custom 1–4 character text badge with color presets.
3. **Color & Label Controls:** Quick color swatches + hex picker for `bg_color` and `text_color`, toggle for `show_label`, and tag chips input.

### 4.3 Webmix (Board) Management
- **Top Tab Bar:** Lists all webmix folders ordered by `_mix.json -> order`.
- **Tab Reordering:** Dragging tabs in the top bar updates `order` across `_mix.json` files.
- **Create / Edit Webmix Modal:**
  - Set `title`, folder slug, `grid_cols` (e.g., 6 to 20), `grid_rows` (e.g., 4 to 14), `theme`, and `background` preset/color.
  - When shrinking grid dimensions, warns if any existing tiles reside outside the new bounds (or offers to relocate them to free cells).
- **Delete Webmix:** Deletes the webmix directory (with confirmation).

### 4.4 Global Instant Search (`Ctrl+K` or `/`)
- Pressing `Ctrl+K` (or clicking the search bar in the header) opens a command-palette overlay.
- Queries an in-memory index of all tiles across all webmixes by `name`, `url`, `tags`, and webmix `title` in `< 2ms`.
- Keyboard navigation (`↑`/`↓`, `Enter` to open URL, `Alt+Enter` to jump to that webmix and highlight the tile).

### 4.5 Live External File Sync (VS Code Integration)
- A background task using `watchfiles.awatch` monitors `./webmixes`.
- Any file creation, modification, rename, or deletion made outside Webaloo (such as editing a JSON file in VS Code or running `git pull`) triggers a Server-Sent Event (`GET /api/events`).
- The browser receives the event and triggers an HTMX partial refresh of the current grid and tab bar without losing UI state.

---

## 5. HTTP & API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Renders main shell and redirects/loads the first ordered webmix. |
| `GET` | `/mix/{mix_slug}` | Renders the full page or HTMX grid partial (`HX-Request`) for `{mix_slug}`. |
| `POST` | `/api/mixes` | Creates a new webmix directory and `_mix.json`. |
| `PUT` | `/api/mixes/{mix_slug}` | Updates `_mix.json` metadata (title, grid dimensions, background, theme). |
| `PUT` | `/api/mixes/reorder` | Updates `order` across webmix `_mix.json` files. |
| `DELETE` | `/api/mixes/{mix_slug}` | Deletes a webmix directory. |
| `POST` | `/api/mixes/{mix_slug}/tiles` | Creates a new `{tile_slug}.json` at `(x, y)`. |
| `PUT` | `/api/mixes/{mix_slug}/tiles/{tile_id}` | Updates tile properties (and renames file if user explicitly requests slug rename). |
| `PUT` | `/api/mixes/{mix_slug}/tiles/{tile_id}/move` | Moves a tile to `(x, y)` or swaps with the occupying tile at `(x, y)`. |
| `POST` | `/api/mixes/{mix_slug}/tiles/{tile_id}/transfer` | Moves a tile file from `{mix_slug}` to another webmix folder. |
| `DELETE` | `/api/mixes/{mix_slug}/tiles/{tile_id}` | Deletes `{tile_id}.json`. |
| `POST` | `/api/icons/fetch` | Fetches metadata & high-res icon for a target URL and caches it in `_icons/`. |
| `POST` | `/api/icons/upload` | Saves a user-uploaded icon image into `_icons/`. |
| `GET` | `/api/search?q=...` | Returns matching tiles across all webmixes for the `Ctrl+K` palette. |
| `GET` | `/api/events` | SSE stream notifying the frontend when files on disk change externally. |
| `GET` | `/icons/{filename}` | Serves cached icons from `./webmixes/_icons/`. |

---

## 6. CLI & Configuration

```bash
# Run with default ./webmixes directory on port 8080
python -m webaloo

# Run with custom directory and port
python -m webaloo --dir C:/path/to/webmixes --port 8765
```

Environment variables:
- `WEBALOO_DIR`: Path to the `webmixes` data directory (default: `./webmixes`).
- `WEBALOO_HOST`: Bind address (default: `127.0.0.1`).
- `WEBALOO_PORT`: Bind port (default: `8080`).
