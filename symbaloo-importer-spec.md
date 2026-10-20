# WEBMIX IMPORTER

Allows to go to a symbaloo webmix like [https://www.symbaloo.com/home/mix/<mix-id>] (or a saved rendered HTML export) and create matching webmixes plus all tiles with URLs and icons for Webaloo.

This is to ease the onboarding of a Symbaloo user into Webaloo.

Tech stack: Python, uv, BeautifulSoup4, httpx.

---

## Architecture & Authentication Approaches

Symbaloo webmix pages use client-side rendering (Elm / SPA) and authenticated user state. To provide complete resiliency across environments, the importer supports multiple ingestion modes:

1. **Local Saved HTML Mode (`file://...` or path to `.html`)**:
   Users can save a loaded Symbaloo page from their desktop browser (using `Ctrl+S` / "Webpage, Complete") and import directly from the saved file. All tile assets in the companion `_files` folder are immediately mapped without requiring live credentials.
2. **Authenticated Session Fetching Mode (Cookies / Bearer token / Headers)**:
   Users can pass their active browser session cookies via `--cookies <cookie_str_or_file>` or `--header "Cookie: ..."` or environment variable `SYMBALOO_COOKIES` to fetch authenticated live webmix pages directly over HTTP/HTTPS.
3. **Webmix Discovery & Batch Mode (`--list`, `--all`, or target single mix)**:
   The importer can inspect the top webmix bar (`tabsBarActiveTab` and sibling tab links), allowing the user to:
   - Output a table of all available webmixes (`--list`).
   - Import the active/single specified webmix (default behavior).
   - Batch import or queue multiple referenced webmixes.

---

## EARS Requirements Specification (`REQ-IMP`)

### EARS Pattern Legend

| Pattern | Syntax Template |
| :--- | :--- |
| **Ubiquitous** | `The <system> shall <response>.` |
| **Event-Driven** | `When <trigger>, the <system> shall <response>.` |
| **State-Driven** | `While <in state>, the <system> shall <response>.` |
| **Unwanted Behavior** | `If <unwanted condition/trigger>, then the <system> shall <response>.` |
| **Optional** | `Where <feature/configuration is active>, the <system> shall <response>.` |
| **Complex** | `While <in state>, when/if <trigger>, (then) the <system> shall <response>.` |

---

### 1. Source Input Ingestion & Authentication (`REQ-IMP-SRC`)

- **REQ-IMP-SRC-001** `[Ubiquitous]`
  The **Symbaloo Importer** shall accept source inputs as public/authenticated Symbaloo webmix URLs (e.g., `https://www.symbaloo.com/home/mix/<id>`), local HTML file paths (`path/to/mix.html`), or `file://` URLs.

- **REQ-IMP-SRC-002** `[Optional]`
  Where session authentication cookies or custom headers are provided (via `--cookies`, `--cookie-file`, or `SYMBALOO_COOKIES`), the **Symbaloo Importer** shall attach them to HTTP requests to access private or user-specific webmixes.

- **REQ-IMP-SRC-003** `[Event-Driven]`
  When given a source input, the **Symbaloo Importer** shall parse the rendered DOM (HTML) and discover all webmix references in the navigation tab bar (titles and target URLs).

- **REQ-IMP-SRC-004** `[Event-Driven]`
  When invoked with `--list`, the **Symbaloo Importer** shall display a formatted table of all discovered webmixes (including index, active status, title, and URL) and exit cleanly without modifying the filesystem.

- **REQ-IMP-SRC-005** `[Unwanted Behavior]`
  If the provided input is invalid, malformed, or points to an unrecognized domain/file, then the **Symbaloo Importer** shall reject the request with a descriptive validation error.

- **REQ-IMP-SRC-006** `[Unwanted Behavior]`
  If an HTTP request fails due to network disconnection or authentication error (HTTP 401/403/404), then the **Symbaloo Importer** shall report an informative error detailing missing authentication and suggest supplying session cookies or local HTML export.

---

### 2. Webmix Selection & Structure Generation (`REQ-IMP-MIX`)

- **REQ-IMP-MIX-001** `[Event-Driven]`
  When importing, the **Symbaloo Importer** shall target the active webmix by default, or all referenced webmixes when `--all` is specified (provided each mix's content or HTML is accessible).

- **REQ-IMP-MIX-002** `[Event-Driven]`
  When webmix metadata is successfully extracted, the **Symbaloo Importer** shall derive a slugified directory name from the webmix title and create a new directory under the root data directory (`./webmixes/<mix_slug>/`).

- **REQ-IMP-MIX-003** `[Unwanted Behavior]`
  If a webmix directory with the target slug already exists in the destination root directory, then the **Symbaloo Importer** shall append an incrementing numeric suffix (e.g., `<mix_slug>-2`) to prevent overwriting existing webmixes.

- **REQ-IMP-MIX-004** `[Ubiquitous]`
  The **Symbaloo Importer** shall generate a `_mix.json` file inside the created webmix directory containing `title`, `order`, `grid_cols`, `grid_rows`, `theme`, `background`, and `created_at` formatted as UTF-8 JSON with 2-space indentation.

- **REQ-IMP-MIX-005** `[Optional]`
  Where the Symbaloo webmix specifies custom grid dimensions (e.g., from `grid-template-columns` and `grid-template-rows` inline CSS styles), the **Symbaloo Importer** shall set `grid_cols` and `grid_rows` in `_mix.json` to match the source grid dimensions (defaulting to 12 × 8 if unspecified).

- **REQ-IMP-MIX-006** `[Optional]`
  Where the Symbaloo webmix defines a custom background color or wallpaper image, the **Symbaloo Importer** shall map the color or download the background asset into `./webmixes/_icons/` and reference it in `_mix.json`.

---

### 3. Tile Coordinate & Attribute Mapping (`REQ-IMP-TILE`)

- **REQ-IMP-TILE-001** `[Event-Driven]`
  When processing each tile from the source webmix (from `li` items in the grid `ul`), the **Symbaloo Importer** shall map CSS `grid-area: <row> / <col>` to 0-indexed integer grid coordinates `(x, y)`: `x = col - 1`, `y = row - 1`.

- **REQ-IMP-TILE-002** `[Ubiquitous]`
  The **Symbaloo Importer** shall extract each tile's target `url`, display `name`, background color (`bg_color` converted from `rgb(...)` to hex `#rrggbb`), text color (`text_color`), and label visibility (`show_label`).

- **REQ-IMP-TILE-003** `[Event-Driven]`
  When generating a tile file, the **Symbaloo Importer** shall create a slugified filename stem from the tile title (e.g., `<tile_slug>.json`) and save the tile definition in the webmix directory.

- **REQ-IMP-TILE-004** `[Unwanted Behavior]`
  If multiple tiles within the imported webmix resolve to the same filename stem, then the **Symbaloo Importer** shall append an incrementing numeric suffix (`<tile_slug>-2.json`) to ensure unique filenames.

- **REQ-IMP-TILE-005** `[Complex]`
  While importing tiles, if a tile specifies coordinate positions outside the target webmix `(grid_cols, grid_rows)` bounds, then the **Symbaloo Importer** shall expand the webmix grid dimensions in `_mix.json` to accommodate the tile without clipping.

---

### 4. Icon & Visual Asset Retrieval (`REQ-IMP-ICON`)

- **REQ-IMP-ICON-001** `[Event-Driven]`
  When a tile contains an associated icon or image (remote HTTP URL or local companion files in `_files/`), the **Symbaloo Importer** shall copy or download the image asset into `./webmixes/_icons/` using a sanitized filename and set `icon_type` to `"cached"` and `icon_url` to `/icons/<filename>`.

- **REQ-IMP-ICON-002** `[Unwanted Behavior]`
  If downloading or reading an icon times out, fails with an error, or returns an unsupported media type, then the **Symbaloo Importer** shall generate a styled monogram badge (`icon_type: "monogram"`) and set `monogram` using the tile name or target hostname without failing the tile import.

- **REQ-IMP-ICON-003** `[Optional]`
  Where a source tile provides no icon image, the **Symbaloo Importer** shall inspect the target URL using Webaloo's favicon discovery service or generate a fallback monogram badge.

---

### 5. Execution & Operational Resiliency (`REQ-IMP-OPS`)

- **REQ-IMP-OPS-001** `[Ubiquitous]`
  The **Symbaloo Importer** shall be executable as a standalone module via `uv run -m webmiximport <source>` and also exposed as a CLI subcommand (e.g., `webaloo import-symbaloo <source>`).

- **REQ-IMP-OPS-002** `[Complex]`
  While an import is in progress, the **Symbaloo Importer** shall write `_mix.json` and all tile files cleanly and trigger search index cache invalidation upon completion.

- **REQ-IMP-OPS-003** `[Event-Driven]`
  When an import operation finishes, the **Symbaloo Importer** shall output a summary reporting the webmix slug, total tiles imported, icon copy/download successes, and any fallback monograms applied.
