from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from webaloo.icons import ALLOWED_ICON_EXTENSIONS, sanitize_icon_filename
from webaloo.storage import Storage, generate_monogram, get_contrast_text_color, slugify

logger = logging.getLogger("webmiximport")


SYMBALOO_COLOR_MAP: dict[str, str] = {
    "white": "#ffffff",
    "black": "#000000",
    "gray": "#64748b",
    "grey": "#64748b",
    "blue": "#2563eb",
    "sky": "#0ea5e9",
    "cyan": "#06b6d4",
    "teal": "#14b8a6",
    "green": "#16a34a",
    "yellow": "#eab308",
    "orange": "#f97316",
    "red": "#dc2626",
    "pink": "#ec4899",
    "purple": "#9333ea",
    "violet": "#7c3aed",
    "indigo": "#4f46e5",
    "brown": "#78350f",
}


def rgb_to_hex(color_str: str | None, default: str = "#1e293b") -> str:
    """Convert rgb(r, g, b) or rgba(...) or named color to a 6-character hex string (#rrggbb)."""
    if not color_str:
        return default
    clean = color_str.strip().lower()
    if clean in SYMBALOO_COLOR_MAP:
        return SYMBALOO_COLOR_MAP[clean]
    if clean.startswith("#"):
        return clean[:7]
    m = re.search(r"rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", clean, re.IGNORECASE)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"#{r:02x}{g:02x}{b:02x}".lower()
    return default


class SymbalooImporter:
    """Engine to parse and import a Symbaloo webmix into Webaloo storage."""

    def __init__(
        self,
        target_root: str | Path | None = None,
        cookies: str | None = None,
        custom_headers: list[str] | None = None,
    ):
        self.storage = Storage(root_dir=target_root)
        self.cookies_str = cookies or os.environ.get("SYMBALOO_COOKIES")
        self.custom_headers = custom_headers or []

    def _build_client_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if self.cookies_str:
            cookie_val = self.cookies_str.strip()
            # If cookies_str points to a file that exists
            cookie_path = Path(cookie_val)
            if cookie_path.is_file():
                cookie_val = cookie_path.read_text(encoding="utf-8").strip()
            headers["Cookie"] = cookie_val

        for h in self.custom_headers:
            if ":" in h:
                k, v = h.split(":", 1)
                headers[k.strip()] = v.strip()
        return headers

    def fetch_source_html(self, source: str) -> tuple[str, str | None, Path | None]:
        """
        Fetch HTML from URL or read from local file.
        Returns (html_content, base_url, companion_files_dir).
        """
        source_clean = source.strip()
        parsed = urlparse(source_clean)

        # Check if local file or file URI
        if parsed.scheme in ("", "file") or Path(source_clean).exists():
            file_path = (
                Path(parsed.path if parsed.scheme == "file" else source_clean)
                .resolve()
            )
            # Remove leading slash on windows file:///C:/path if needed
            if os.name == "nt" and str(file_path).startswith("\\") and len(str(file_path)) > 2 and str(file_path)[2] == ":":
                file_path = Path(str(file_path).lstrip("\\"))

            if not file_path.is_file():
                raise FileNotFoundError(f"Source file not found: {source_clean}")

            # Look for companion folder created by browser save
            # e.g., 'sample_files' or '<name>_files'
            candidate_files_dirs = [
                file_path.parent / f"{file_path.stem}_files",
                file_path.parent / f"{file_path.name}_files",
            ]
            companion_dir: Path | None = None
            for cand in candidate_files_dirs:
                if cand.is_dir():
                    companion_dir = cand
                    break

            html = file_path.read_text(encoding="utf-8", errors="ignore")
            return html, None, companion_dir

        if parsed.scheme in ("http", "https"):
            if not parsed.hostname or "symbaloo" not in parsed.hostname.lower():
                raise ValueError(
                    f"URL '{source_clean}' does not point to a recognized Symbaloo domain."
                )

            headers = self._build_client_headers()
            try:
                with httpx.Client(
                    follow_redirects=True,
                    verify=False,
                    timeout=httpx.Timeout(15.0),
                    headers=headers,
                ) as client:
                    resp = client.get(source_clean)
                    if resp.status_code in (401, 403):
                        raise PermissionError(
                            f"HTTP {resp.status_code}: Access denied for {source_clean}. "
                            "Symbaloo page requires authentication. Pass session cookies with --cookies."
                        )
                    if resp.status_code == 404:
                        raise FileNotFoundError(
                            f"HTTP 404: Webmix not found at {source_clean}."
                        )
                    if resp.status_code >= 400:
                        raise RuntimeError(
                            f"HTTP {resp.status_code} error fetching webmix from {source_clean}."
                        )
                    return resp.text, str(resp.url), None
            except httpx.RequestError as exc:
                raise ConnectionError(f"Network error requesting {source_clean}: {exc}") from exc

        raise ValueError(f"Invalid or unsupported source specification: '{source}'")

    def discover_webmixes_from_html(
        self, html: str, base_url: str | None = None
    ) -> list[dict[str, Any]]:
        """Parse navigation tab bar to find all webmix references."""
        soup = BeautifulSoup(html, "html.parser")
        mixes: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for a in soup.find_all("a", href=True):
            href = str(a["href"]).strip()
            if "/home/mix/" not in href or href.endswith("#mainContent"):
                continue

            full_url = urljoin(base_url or "https://www.symbaloo.com", href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            title = a.get_text(strip=True)
            if not title:
                title_span = a.find("span")
                if title_span:
                    title = title_span.get_text(strip=True)
            if not title:
                continue

            is_active = "tabsBarActiveTab" in str(a.get("id", ""))
            data_id = str(a.get("data-id", "")).strip() or None
            mixes.append({
                "title": title,
                "url": full_url,
                "desktop_id": data_id,
                "is_active": is_active,
            })

        return mixes

    def parse_webmix_data(
        self, html: str, base_url: str | None, companion_dir: Path | None
    ) -> dict[str, Any]:
        """Extract grid dimensions, webmix title, and all tiles from HTML."""
        soup = BeautifulSoup(html, "html.parser")

        # Determine webmix title
        active_tab = soup.find("a", id="tabsBarActiveTab")
        title = "Imported Webmix"
        if active_tab and active_tab.get_text(strip=True):
            title = active_tab.get_text(strip=True)
        elif soup.title and soup.title.string:
            title_text = soup.title.string.strip()
            # Often 'Symbaloo: Bookmarks & Favorites...' or '<Title> - Symbaloo'
            if ":" in title_text:
                title = title_text.split(":", 1)[1].split("-", 1)[0].strip()
            else:
                title = title_text.split("-", 1)[0].strip()

        # Locate grid <ul> container
        # Look for <ul> containing <li> with grid-area or style with grid-template-columns
        grid_ul = None
        for ul in soup.find_all("ul"):
            style = ul.get("style", "")
            if "grid-template-columns" in style and "grid-template-rows" in style:
                grid_ul = ul
                break

        if not grid_ul:
            # Fallback: look for <li> with grid-area style
            for li in soup.find_all("li", style=True):
                if "grid-area" in li["style"]:
                    grid_ul = li.parent
                    break

        if not grid_ul:
            raise ValueError("Could not find a Symbaloo grid container in the HTML.")

        # Determine grid cols and rows from CSS
        grid_cols = 12
        grid_rows = 8
        ul_style = grid_ul.get("style", "")
        m_cols = re.search(r"grid-template-columns:\s*repeat\((\d+)", ul_style)
        if m_cols:
            grid_cols = int(m_cols.group(1))
        m_rows = re.search(r"grid-template-rows:\s*repeat\((\d+)", ul_style)
        if m_rows:
            grid_rows = int(m_rows.group(1))

        # Check background of webmix container or ancestors
        background = "#0f172a"
        cur = grid_ul
        for _ in range(8):
            if not cur:
                break
            bg_st = cur.get("style", "")
            if "background-color" in bg_st:
                m_bg = re.search(r"background-color:\s*([^;]+)", bg_st)
                if m_bg:
                    background = rgb_to_hex(m_bg.group(1), default=background)
                    break
            cur = cur.parent

        # Extract tiles
        raw_tiles: list[dict[str, Any]] = []
        for li in grid_ul.find_all("li"):
            style = li.get("style", "")
            if not style or "grid-area" not in style:
                continue

            # grid-area: row_start / col_start / row_end / col_end
            m_grid = re.search(
                r"grid-area:\s*(\d+)\s*/\s*(\d+)(?:\s*/\s*(\d+)\s*/\s*(\d+))?",
                style,
            )
            if not m_grid:
                continue

            row_start = int(m_grid.group(1))
            col_start = int(m_grid.group(2))
            row_end = int(m_grid.group(3)) if m_grid.group(3) else row_start + 1
            col_end = int(m_grid.group(4)) if m_grid.group(4) else col_start + 1

            x = col_start - 1
            y = row_start - 1
            w = max(1, col_end - col_start)
            h = max(1, row_end - row_start)

            a_tag = li.find("a")
            if not a_tag:
                continue

            target_url = a_tag.get("href", "").strip()
            if not target_url or target_url.startswith("javascript:"):
                continue

            # Tile display name
            p_tag = a_tag.find("p")
            if p_tag and p_tag.get_text(strip=True):
                tile_name = p_tag.get_text(strip=True)
            else:
                tile_name = a_tag.get_text(strip=True)
            if not tile_name:
                tile_name = urlparse(target_url).hostname or "Bookmark"

            # Tile background color
            a_style = a_tag.get("style", "")
            m_tile_bg = re.search(r"background-color:\s*([^;]+)", a_style)
            bg_color = rgb_to_hex(m_tile_bg.group(1) if m_tile_bg else None, default="#1e293b")

            # Check text color based on background luminance
            text_color = get_contrast_text_color(bg_color)

            # Icon / Image
            img_tag = a_tag.find("img")
            img_src = img_tag.get("src") if img_tag else None

            raw_tiles.append({
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "url": target_url,
                "name": tile_name,
                "bg_color": bg_color,
                "text_color": text_color,
                "show_label": True,
                "img_src": img_src,
            })

        return {
            "title": title,
            "grid_cols": grid_cols,
            "grid_rows": grid_rows,
            "background": background,
            "tiles": raw_tiles,
        }

    def _resolve_icon(
        self,
        img_src: str | None,
        tile_name: str,
        target_url: str,
        base_url: str | None,
        companion_dir: Path | None,
    ) -> tuple[str, str | None, str]:
        """
        Resolve tile icon.
        Returns (icon_type, icon_url, monogram).
        """
        monogram = generate_monogram(tile_name, target_url)
        if not img_src:
            return "monogram", None, monogram

        clean_src = img_src.strip()

        # Case 1: Local companion file in _files directory
        # e.g., './<files>/pencil.png' or '<files>/pencil.png'
        if companion_dir and not clean_src.startswith(("http://", "https://")):
            src_name = Path(clean_src).name
            local_asset_path = companion_dir / src_name
            if local_asset_path.is_file():
                try:
                    safe_name = sanitize_icon_filename(src_name, prefix=slugify(tile_name))
                    dest_path = self.storage.icons_dir / safe_name
                    # Only copy if destination doesn't exist or same file
                    if not dest_path.exists():
                        shutil.copy2(local_asset_path, dest_path)
                    return "cached", f"/icons/{safe_name}", monogram
                except Exception as exc:
                    logger.warning("Failed to copy companion icon %s: %s", local_asset_path, exc)

        # Case 2: Remote URL
        full_img_url = urljoin(base_url or "https://www.symbaloo.com", clean_src)
        parsed_img = urlparse(full_img_url)
        if parsed_img.scheme in ("http", "https"):
            try:
                headers = self._build_client_headers()
                with httpx.Client(
                    follow_redirects=True,
                    verify=False,
                    timeout=httpx.Timeout(5.0),
                    headers=headers,
                ) as client:
                    resp = client.get(full_img_url)
                    if resp.status_code == 200 and len(resp.content) >= 32:
                        raw_stem = Path(parsed_img.path).stem or slugify(tile_name)
                        raw_ext = Path(parsed_img.path).suffix.lower()
                        if raw_ext not in ALLOWED_ICON_EXTENSIONS:
                            raw_ext = ".png"
                        safe_name = sanitize_icon_filename(f"{raw_stem}{raw_ext}", prefix="sym-icon")
                        dest_path = self.storage.icons_dir / safe_name
                        dest_path.write_bytes(resp.content)
                        return "cached", f"/icons/{safe_name}", monogram
            except Exception as exc:
                logger.debug("Failed to download remote icon %s: %s", full_img_url, exc)

        # Fallback to styled monogram
        return "monogram", None, monogram

    def fetch_desktop_via_graphql(self, desktop_id: str) -> dict[str, Any]:
        """Fetch desktop/webmix details from Symbaloo GraphQL API."""
        endpoint = "https://www.symbaloo.com/graphql"
        headers = self._build_client_headers()
        headers.update({
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Origin": "https://www.symbaloo.com",
            "Referer": "https://www.symbaloo.com/",
        })
        payload = [
            {
                "operationName": "Pages/Home/Queries.gql:GetDesktopDetails",
                "variables": {"desktopId": desktop_id},
            }
        ]
        with httpx.Client(
            follow_redirects=True,
            verify=False,
            timeout=httpx.Timeout(15.0),
            headers=headers,
        ) as client:
            resp = client.post(endpoint, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"GraphQL query failed with HTTP {resp.status_code}: {resp.text[:200]}"
                )
            result = resp.json()
            if isinstance(result, list) and len(result) > 0:
                data = result[0].get("data", {})
                desktop = data.get("desktop")
                if desktop:
                    return desktop
            raise ValueError(f"No desktop details returned in GraphQL response: {result}")

    def import_desktop_data(
        self,
        desktop_data: dict[str, Any],
        custom_slug: str | None = None,
        base_url: str | None = None,
        companion_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Convert a parsed webmix data dictionary (or GraphQL desktop object) into Webaloo files."""
        # Support both parse_webmix_data dict and GraphQL desktop dict
        if "smarks" in desktop_data:
            # GraphQL schema
            title = desktop_data.get("name") or "Imported Webmix"
            grid_cols = int(desktop_data.get("width") or 10)
            grid_rows = int(desktop_data.get("height") or 6)
            bg_raw = desktop_data.get("background") or {}
            background = rgb_to_hex(bg_raw.get("color"), default="#0f172a")

            raw_tiles: list[dict[str, Any]] = []
            for smark in desktop_data.get("smarks") or []:
                tile_name = smark.get("name") or "Bookmark"
                typed = smark.get("typed") or {}
                tile_url = typed.get("url") or "#"
                x = int(smark.get("x") or 0)
                y = int(smark.get("y") or 0)
                w = int(smark.get("width") or 1)
                h = int(smark.get("height") or 1)
                tile_bg = rgb_to_hex(smark.get("color"), default="#1e293b")
                img_src = smark.get("image")

                raw_tiles.append({
                    "name": tile_name,
                    "url": tile_url,
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h,
                    "bg_color": tile_bg,
                    "text_color": get_contrast_text_color(tile_bg),
                    "show_label": True,
                    "img_src": img_src,
                })
        else:
            # parse_webmix_data schema
            title = desktop_data["title"]
            grid_cols = desktop_data["grid_cols"]
            grid_rows = desktop_data["grid_rows"]
            background = desktop_data["background"]
            raw_tiles = desktop_data["tiles"]

        # Expand grid bounds if any tile extends outside initial bounds (REQ-IMP-TILE-005)
        for t in raw_tiles:
            grid_cols = max(grid_cols, t["x"] + t["w"])
            grid_rows = max(grid_rows, t["y"] + t["h"])

        # Determine non-conflicting webmix directory slug (REQ-IMP-MIX-002)
        base_slug = slugify(custom_slug or title, fallback="mix")
        target_slug = base_slug
        mix_dir = self.storage.root_dir / target_slug
        counter = 2
        while mix_dir.exists():
            target_slug = f"{base_slug}-{counter}"
            mix_dir = self.storage.root_dir / target_slug
            counter += 1

        mix_dir.mkdir(parents=True, exist_ok=True)
        self.storage.icons_dir.mkdir(parents=True, exist_ok=True)

        # Determine order
        existing_mixes = self.storage.list_mixes()
        order = (max((m["order"] for m in existing_mixes), default=-1) + 1) if existing_mixes else 0

        # Generate _mix.json (REQ-IMP-MIX-003, REQ-IMP-MIX-004)
        mix_meta = {
            "title": title,
            "order": order,
            "grid_cols": grid_cols,
            "grid_rows": grid_rows,
            "theme": "dark",
            "background": background,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        mix_json_path = mix_dir / "_mix.json"
        mix_json_path.write_text(json.dumps(mix_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        # Import tiles (REQ-IMP-TILE, REQ-IMP-ICON)
        used_stems: set[str] = set()
        cached_icons_count = 0
        monograms_count = 0

        for t in raw_tiles:
            tile_name = t["name"]
            stem = slugify(tile_name, fallback="tile")
            if stem in used_stems:
                c = 2
                while f"{stem}-{c}" in used_stems:
                    c += 1
                stem = f"{stem}-{c}"
            used_stems.add(stem)

            icon_type, icon_url, monogram = self._resolve_icon(
                t.get("img_src"),
                tile_name=tile_name,
                target_url=t["url"],
                base_url=base_url,
                companion_dir=companion_dir,
            )

            if icon_type == "cached":
                cached_icons_count += 1
            else:
                monograms_count += 1

            tile_data = {
                "id": stem,
                "name": tile_name,
                "url": t["url"],
                "x": t["x"],
                "y": t["y"],
                "w": t["w"],
                "h": t["h"],
                "bg_color": t["bg_color"],
                "text_color": t["text_color"],
                "show_label": t["show_label"],
                "icon_type": icon_type,
                "icon": None,
                "icon_url": icon_url,
                "monogram": monogram,
                "tags": [],
                "target": "_blank",
            }

            tile_path = mix_dir / f"{stem}.json"
            tile_path.write_text(json.dumps(tile_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        self.storage.mark_internal_write()
        self.storage.rebuild_search_index()

        return {
            "slug": target_slug,
            "title": title,
            "grid_cols": grid_cols,
            "grid_rows": grid_rows,
            "tiles_count": len(raw_tiles),
            "cached_icons": cached_icons_count,
            "monograms": monograms_count,
            "mix_dir": str(mix_dir),
        }

    def import_webmix(
        self,
        source: str,
        custom_slug: str | None = None,
    ) -> dict[str, Any]:
        """Execute complete webmix import from source URL or file."""
        html, base_url, companion_dir = self.fetch_source_html(source)
        data = self.parse_webmix_data(html, base_url=base_url, companion_dir=companion_dir)
        return self.import_desktop_data(
            data,
            custom_slug=custom_slug,
            base_url=base_url,
            companion_dir=companion_dir,
        )

    def import_all_webmixes(
        self,
        source: str,
    ) -> list[dict[str, Any]]:
        """Import all webmixes discovered from the source page."""
        html, base_url, companion_dir = self.fetch_source_html(source)
        discovered = self.discover_webmixes_from_html(html, base_url=base_url)

        if not discovered:
            # Fallback to importing just the single source
            return [self.import_webmix(source)]

        results: list[dict[str, Any]] = []

        # First, import the active mix from the local HTML/DOM if present
        active_entry = next((m for m in discovered if m.get("is_active")), None)
        if active_entry:
            try:
                active_res = self.import_webmix(source)
                results.append(active_res)
            except Exception as exc:
                logger.warning("Failed importing active webmix from HTML: %s", exc)

        # For remaining webmixes, fetch via GraphQL if desktop_id is present
        for mix in discovered:
            if mix.get("is_active") and any(r["title"] == mix["title"] for r in results):
                continue

            desktop_id = mix.get("desktop_id")
            title = mix.get("title", "Untitled")

            if not desktop_id:
                logger.info("Skipping '%s': no desktop_id discovered.", title)
                continue

            try:
                desktop_details = self.fetch_desktop_via_graphql(desktop_id)
                res = self.import_desktop_data(
                    desktop_details,
                    base_url=base_url,
                    companion_dir=companion_dir,
                )
                results.append(res)
            except Exception as exc:
                logger.warning("Failed importing webmix '%s' via GraphQL: %s", title, exc)
                results.append({
                    "title": title,
                    "error": str(exc),
                })

        return results


def discover_webmixes(
    source: str, importer: SymbalooImporter | None = None
) -> list[dict[str, Any]]:
    """Convenience helper to discover webmixes from source."""
    imp = importer or SymbalooImporter()
    html, base_url, _ = imp.fetch_source_html(source)
    return imp.discover_webmixes_from_html(html, base_url=base_url)


def import_symbaloo(
    source: str,
    target_root: str | Path | None = None,
    cookies: str | None = None,
    custom_headers: list[str] | None = None,
    custom_slug: str | None = None,
    all_mixes: bool = False,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Convenience function to import a Symbaloo webmix (or all discovered webmixes)."""
    importer = SymbalooImporter(
        target_root=target_root,
        cookies=cookies,
        custom_headers=custom_headers,
    )
    if all_mixes:
        return importer.import_all_webmixes(source)
    return importer.import_webmix(source, custom_slug=custom_slug)
