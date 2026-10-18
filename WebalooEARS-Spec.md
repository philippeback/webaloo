# Webaloo Requirements Specification (EARS)

This document formalizes the requirements from [WebalooSpec.md](file:///C:/Dev/github/philippeback/webaloo/WebalooSpec.md) using the **Easy Approach to Requirements Syntax (EARS)**.

---

## EARS Pattern Legend

| Pattern | Syntax Template |
| :--- | :--- |
| **Ubiquitous** | `The <system> shall <response>.` |
| **Event-Driven** | `When <trigger>, the <system> shall <response>.` |
| **State-Driven** | `While <in state>, the <system> shall <response>.` |
| **Unwanted Behavior** | `If <unwanted condition/trigger>, then the <system> shall <response>.` |
| **Optional** | `Where <feature/configuration is active>, the <system> shall <response>.` |
| **Complex** | `While <in state>, when/if <trigger>, (then) the <system> shall <response>.` |

---

## 1. Filesystem & Data Model Requirements (`REQ-FS`)

- **REQ-FS-001** `[Ubiquitous]`
  The **Webaloo Backend** shall store all webmixes and tiles directly on the local filesystem without requiring an external SQL or NoSQL database.

- **REQ-FS-002** `[Ubiquitous]`
  The **Webaloo Backend** shall use `./webmixes` in the current working directory as the default root data directory.

- **REQ-FS-003** `[Optional]`
  Where the `--dir` CLI argument or the `WEBALOO_DIR` environment variable is provided, the **Webaloo Backend** shall use the specified filesystem path as the root data directory, with `--dir` taking precedence over `WEBALOO_DIR`.

- **REQ-FS-004** `[Event-Driven]`
  When the **Webaloo Backend** starts and the root data directory does not exist, the **Webaloo Backend** shall create the root data directory, the `_icons/` subdirectory, and a default webmix (`default/_mix.json`).

- **REQ-FS-005** `[Ubiquitous]`
  The **Webaloo Backend** shall treat every subdirectory inside the root data directory whose name does not start with `.` or `_` as a distinct webmix.

- **REQ-FS-006** `[Ubiquitous]`
  The **Webaloo Backend** shall store webmix metadata in a `_mix.json` file inside each webmix directory containing `title`, `order`, `grid_cols`, `grid_rows`, `theme`, `background`, and `created_at`.

- **REQ-FS-007** `[Ubiquitous]`
  The **Webaloo Backend** shall treat every `.json` file inside a webmix directory whose filename does not start with `_` as an individual tile.

- **REQ-FS-008** `[Ubiquitous]`
  The **Webaloo Backend** shall derive each tile's unique identifier (`id`) within its webmix directly from the `.json` filename stem (e.g., `tradingview.json` $\rightarrow$ `id = "tradingview"`).

- **REQ-FS-009** `[Ubiquitous]`
  The **Webaloo Backend** shall serialize all `_mix.json` and tile `.json` files using UTF-8 encoding and 2-space indentation so that files remain human-readable and Git-diffable.

- **REQ-FS-010** `[Unwanted Behavior]`
  If a webmix directory is missing its `_mix.json` file when scanned, then the **Webaloo Backend** shall generate a default `_mix.json` using the directory name as the title and `12 × 8` as the default grid dimensions.

- **REQ-FS-011** `[Unwanted Behavior]`
  If a tile `.json` file contains malformed JSON or invalid coordinate types when scanned, then the **Webaloo Backend** shall log a warning and skip rendering that file without crashing or blocking the rest of the webmix.

---

## 2. Webmix (Board) Management Requirements (`REQ-MIX`)

- **REQ-MIX-001** `[Ubiquitous]`
  The **Webaloo UI** shall display all discovered webmixes in the top navigation tab bar sorted in ascending order by their `_mix.json` `order` value.

- **REQ-MIX-002** `[Event-Driven]`
  When a user clicks a webmix tab in the top navigation bar, the **Webaloo UI** shall fetch and render that webmix's grid via HTMX (`GET /mix/{mix_slug}`) and update the browser URL without a full page reload.

- **REQ-MIX-003** `[Event-Driven]`
  When a user submits the Create Webmix form with a title and grid configuration, the **Webaloo Backend** shall slugify the title into a directory name, create the directory and `_mix.json`, and return the new webmix view.

- **REQ-MIX-004** `[Unwanted Behavior]`
  If a user attempts to create a webmix whose slugified directory name already exists, then the **Webaloo Backend** shall append an incrementing numeric suffix (e.g., `trading-2`) or return a validation error if an explicit duplicate slug was specified.

- **REQ-MIX-005** `[Event-Driven]`
  When a user drags and drops tabs in the top tab bar to reorder them, the **Webaloo Backend** shall update the `order` attribute in each affected webmix's `_mix.json` file (`PUT /api/mixes/reorder`).

- **REQ-MIX-006** `[Event-Driven]`
  When a user updates a webmix's `title`, `grid_cols`, `grid_rows`, `theme`, or `background` in the Edit Webmix modal, the **Webaloo Backend** shall persist the updated fields to `_mix.json` and re-render the board.

- **REQ-MIX-007** `[Complex]`
  While editing a webmix's grid dimensions, if the new `grid_cols` or `grid_rows` is smaller than the current dimensions and one or more existing tiles have `(x, y)` coordinates outside the new bounds, then the **Webaloo UI** shall warn the user and offer to relocate out-of-bounds tiles to the nearest empty slots before saving.

- **REQ-MIX-008** `[Event-Driven]`
  When a user confirms deletion of a webmix, the **Webaloo Backend** shall delete the corresponding webmix directory and its tile `.json` files while preserving shared icons in `_icons/`.

---

## 3. Symbaloo-Style 2D Grid & Spatial Requirements (`REQ-GRID`)

- **REQ-GRID-001** `[Ubiquitous]`
  The **Webaloo UI** shall render the active webmix as a fixed 2D matrix of `grid_cols` columns by `grid_rows` rows where every coordinate `(x, y)` (`0 <= x < grid_cols`, `0 <= y < grid_rows`) occupies a fixed spatial slot.

- **REQ-GRID-002** `[Ubiquitous]`
  The **Webaloo UI** shall preserve empty grid slots (`float: true` behavior) and shall not automatically compact or gravity-pack tiles upward or leftward.

- **REQ-GRID-003** `[State-Driven]`
  While a grid coordinate `(x, y)` is unoccupied by any tile, the **Webaloo UI** shall render an interactive empty cell placeholder at `(x, y)` that highlights on hover.

- **REQ-GRID-004** `[Event-Driven]`
  When a user drags a tile from `(x_1, y_1)` and drops it onto an unoccupied slot `(x_2, y_2)`, the **Webaloo Backend** shall update the tile's `x` to `x_2` and `y` to `y_2` in its `.json` file on disk.

- **REQ-GRID-005** `[Event-Driven]`
  When a user drags a tile from `(x_1, y_1)` and drops it onto a slot `(x_2, y_2)` that is currently occupied by another tile, the **Webaloo Backend** shall atomically swap the `(x, y)` coordinates of both tiles in their respective `.json` files on disk.

- **REQ-GRID-006** `[Unwanted Behavior]`
  If a tile drag-and-drop update (`PUT /api/mixes/{mix_slug}/tiles/{tile_id}/move`) fails or targets out-of-bounds coordinates, then the **Webaloo UI** shall revert the dragged tile to its previous `(x, y)` slot and display an error notification.

---

## 4. Tile Interaction & Lifecycle Requirements (`REQ-TILE`)

- **REQ-TILE-001** `[Event-Driven]`
  When a user left-clicks an occupied tile (without dragging), the **Webaloo UI** shall navigate to the tile's `url` using the target behavior specified in the tile's `target` property (`_blank` by default).

- **REQ-TILE-002** `[Ubiquitous]`
  The **Webaloo UI** shall allow tiles to link to public HTTPS/HTTP URLs, local loopback addresses (`localhost`, `127.0.0.1`), private LAN subnet URLs (`192.168.x.x`, `10.x.x.x`), and custom application URI schemes (e.g., `vscode://`, `obsidian://`).

- **REQ-TILE-003** `[Event-Driven]`
  When a user left-clicks an unoccupied grid cell at `(x, y)`, the **Webaloo UI** shall open the Create Tile modal pre-populated with coordinates `(x, y)`.

- **REQ-TILE-004** `[Event-Driven]`
  When a user submits the Create Tile modal, the **Webaloo Backend** shall generate a human-readable slugified filename from the tile's `name` (e.g., `TradingView` $\rightarrow$ `tradingview.json`) and write the tile JSON payload to the active webmix directory.

- **REQ-TILE-005** `[Unwanted Behavior]`
  If creating a new tile results in a filename stem that already exists in the same webmix directory, then the **Webaloo Backend** shall append an incrementing numeric suffix (`{slug}-2.json`, `{slug}-3.json`, etc.) to guarantee uniqueness.

- **REQ-TILE-006** `[Event-Driven]`
  When a user right-clicks an occupied tile or clicks its hover action button, the **Webaloo UI** shall display a context menu with options to **Edit**, **Duplicate**, **Move to Webmix**, and **Delete** the tile.

- **REQ-TILE-007** `[Event-Driven]`
  When a user edits and saves an existing tile in the Tile Editor modal, the **Webaloo Backend** shall update the tile's `.json` file on disk and refresh the tile in the grid.

- **REQ-TILE-008** `[Event-Driven]`
  When a user selects **Duplicate** on a tile, the **Webaloo Backend** shall create a copy of the tile's JSON at the nearest unoccupied `(x, y)` coordinate in the same webmix with a unique slugified filename.

- **REQ-TILE-009** `[Unwanted Behavior]`
  If a user selects **Duplicate** on a tile when all `grid_cols × grid_rows` slots in the active webmix are already occupied, then the **Webaloo Backend** shall reject the duplication and notify the user that the board is full.

- **REQ-TILE-010** `[Event-Driven]`
  When a user selects **Move to Webmix** and chooses a destination webmix, the **Webaloo Backend** shall move the tile's `.json` file to the destination webmix directory at its existing `(x, y)` coordinate if free, or at the first available unoccupied coordinate in the destination webmix.

- **REQ-TILE-011** `[Event-Driven]`
  When a user selects **Delete** on a tile, the **Webaloo Backend** shall remove the corresponding `{tile_id}.json` file from the webmix directory on disk and return the `(x, y)` slot to an empty state.

---

## 5. Favicon Discovery & Tile Appearance Requirements (`REQ-ICON`)

- **REQ-ICON-001** `[Ubiquitous]`
  The **Webaloo Backend** shall store all auto-fetched site icons and user-uploaded tile icons inside `./webmixes/_icons/` and serve them via `/icons/{filename}` so that the data folder remains portable and works offline.

- **REQ-ICON-002** `[Event-Driven]`
  When a user enters or pastes a valid HTTP/HTTPS URL in the Tile Editor modal, the **Webaloo Backend** shall asynchronously inspect the target page (`POST /api/icons/fetch`) to extract the page title and highest-resolution icon (`apple-touch-icon`, web manifest icon, or `<link rel="icon">`) and save the icon into `./webmixes/_icons/`.

- **REQ-ICON-003** `[Unwanted Behavior]`
  If fetching the icon from the target URL times out, fails due to network/TLS errors, or yields no icon, then the **Webaloo Backend** shall fall back to generating a styled monogram badge from the tile's name or domain without blocking tile creation.

- **REQ-ICON-004** `[Ubiquitous]`
  The **Tile Editor UI** shall provide four selectable icon modes for any tile:
  1. **Cached Site / Uploaded Icon** (`icon_type: "cached"`),
  2. **Lucide Vector Icon Picker** (`icon_type: "lucide"`),
  3. **External Image URL** (`icon_type: "external"`), and
  4. **Styled Monogram Badge** (`icon_type: "monogram"`).

- **REQ-ICON-005** `[Event-Driven]`
  When a user uploads a custom image file (`.png`, `.svg`, `.ico`, `.webp`, `.jpg`) in the Tile Editor modal, the **Webaloo Backend** shall sanitize the filename, store the file in `./webmixes/_icons/`, and bind `icon_url` to `/icons/{filename}`.

- **REQ-ICON-006** `[Ubiquitous]`
  The **Tile Editor UI** shall allow the user to customize `bg_color`, `text_color`, `show_label`, and `tags` with a live preview of the tile before saving.

---

## 6. Global Instant Search Requirements (`REQ-SRCH`)

- **REQ-SRCH-001** `[Event-Driven]`
  When a user presses `Ctrl+K` (or `/` when not focused in an input field) or clicks the top search button, the **Webaloo UI** shall open the global search command palette and focus the search input.

- **REQ-SRCH-002** `[Event-Driven]`
  When a user types a query into the global search input, the **Webaloo Backend** (`GET /api/search?q=...`) shall filter the in-memory tile index across all webmixes by matching against tile `name`, `url`, `tags`, and webmix `title`.

- **REQ-SRCH-003** `[State-Driven]`
  While the global search palette is open, the **Webaloo UI** shall allow the user to navigate matching tiles using the `↑` and `↓` arrow keys, press `Enter` to open the selected tile's URL, or press `Alt+Enter` to switch to the tile's webmix and highlight its slot on the grid.

---

## 7. Live External File Synchronization Requirements (`REQ-SYNC`)

- **REQ-SYNC-001** `[State-Driven]`
  While the **Webaloo Backend** is running, the **File Watcher Service** shall continuously monitor the root data directory (`./webmixes`) for file and directory creations, modifications, renames, and deletions.

- **REQ-SYNC-002** `[Event-Driven]`
  When a `.json` file or webmix folder inside the root data directory is modified externally (e.g., saved in VS Code or updated via Git), the **Webaloo Backend** shall update its in-memory search cache and broadcast a reload event over the Server-Sent Events stream (`GET /api/events`).

- **REQ-SYNC-003** `[Complex]`
  While a user is viewing a webmix in the browser and no modal dialog is open, when the browser receives an SSE reload event from `/api/events`, the **Webaloo UI** shall refresh the top tab bar and active grid partial via HTMX without losing scroll position or requiring a manual browser refresh.

- **REQ-SYNC-004** `[Complex]`
  While a user has an active modal dialog open (such as the Tile Editor), when an external SSE reload event arrives, the **Webaloo UI** shall defer refreshing the underlying grid until the modal is closed or show a non-intrusive sync indicator so unsaved form input is not lost.
