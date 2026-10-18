from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("webaloo.storage")


def slugify(value: str, fallback: str = "item") -> str:
    """Convert a string into a clean, lowercase, hyphen-separated filesystem slug."""
    if not value:
        return fallback
    slug = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-_")
    if not slug or slug.startswith(".") or slug.startswith("_"):
        slug = f"{fallback}-{slug}".strip("-_")
    return slug or fallback


def generate_monogram(name: str, url: str = "") -> str:
    """Generate a 1-4 character monogram from a tile name or URL."""
    clean = (name or "").strip()
    if clean:
        words = [w for w in re.split(r"[\s\-_/]+", clean) if w]
        if len(words) >= 2:
            return "".join(w[0] for w in words[:3]).upper()
        return clean[:2].upper()
    if url:
        host = re.sub(r"^https?://(www\.)?", "", url.strip().lower()).split("/")[0]
        return (host[:2] or "WB").upper()
    return "WB"


class BoardFullError(Exception):
    """Raised when a webmix has no free grid slots remaining."""


class OutOfBoundsError(Exception):
    """Raised when coordinates are outside webmix grid dimensions or tiles would be clipped."""

    def __init__(self, message: str, affected_tiles: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.affected_tiles = affected_tiles or []


class Storage:
    """Filesystem-backed storage manager for Webaloo webmixes and tiles."""

    def __init__(self, root_dir: str | Path | None = None):
        if root_dir is None:
            env_dir = os.environ.get("WEBALOO_DIR")
            root_dir = Path(env_dir) if env_dir else Path.cwd() / "webmixes"
        self.root_dir = Path(root_dir).resolve()
        self.icons_dir = self.root_dir / "_icons"
        self._search_cache: list[dict[str, Any]] = []
        self._cache_dirty: bool = True
        self._last_internal_write: float = 0.0
        self.ensure_initialized()

    def mark_internal_write(self) -> None:
        """Record timestamp of an internal write and invalidate search cache."""
        self._last_internal_write = time.monotonic()
        self._cache_dirty = True

    def invalidate_cache(self) -> None:
        """Mark the in-memory search index as needing refresh."""
        self._cache_dirty = True

    def ensure_initialized(self) -> None:
        """REQ-FS-004: Ensure root data directory, _icons/, and default/_mix.json exist."""
        root_existed = self.root_dir.exists()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.icons_dir.mkdir(parents=True, exist_ok=True)

        if not root_existed:
            default_dir = self.root_dir / "default"
            default_dir.mkdir(parents=True, exist_ok=True)
            mix_file = default_dir / "_mix.json"
            if not mix_file.exists():
                self._write_json(
                    mix_file,
                    self._default_mix_metadata(title="Default", order=0),
                )
        else:
            # Ensure at least one webmix exists if root directory has no webmix subdirectories
            has_mix = any(
                p.is_dir() and not p.name.startswith(".") and not p.name.startswith("_")
                for p in self.root_dir.iterdir()
            )
            if not has_mix:
                default_dir = self.root_dir / "default"
                default_dir.mkdir(parents=True, exist_ok=True)
                self._write_json(
                    default_dir / "_mix.json",
                    self._default_mix_metadata(title="Default", order=0),
                )

    @staticmethod
    def _default_mix_metadata(
        title: str,
        order: int = 0,
        grid_cols: int = 12,
        grid_rows: int = 8,
        theme: str = "dark",
        background: str = "#0f172a",
    ) -> dict[str, Any]:
        return {
            "title": title,
            "order": int(order),
            "grid_cols": int(grid_cols),
            "grid_rows": int(grid_rows),
            "theme": theme,
            "background": background,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        """REQ-FS-009: Write JSON using UTF-8 and 2-space indentation."""
        self.mark_internal_write()
        content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        path.write_text(content, encoding="utf-8")

    def _is_valid_mix_dir(self, path: Path) -> bool:
        """REQ-FS-005: Every subdirectory not starting with '.' or '_' is a webmix."""
        return path.is_dir() and not path.name.startswith(".") and not path.name.startswith("_")

    def _load_or_create_mix_meta(self, mix_dir: Path, default_order: int = 999) -> dict[str, Any]:
        """REQ-FS-006 & REQ-FS-010: Load _mix.json or generate default if missing/corrupt."""
        mix_file = mix_dir / "_mix.json"
        default_title = mix_dir.name.replace("-", " ").replace("_", " ").title()
        if not mix_file.exists():
            meta = self._default_mix_metadata(title=default_title, order=default_order)
            self._write_json(mix_file, meta)
        else:
            try:
                raw = json.loads(mix_file.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("_mix.json root must be an object")
                meta = {
                    "title": str(raw.get("title") or default_title),
                    "order": int(raw.get("order", default_order)),
                    "grid_cols": max(1, int(raw.get("grid_cols", 12))),
                    "grid_rows": max(1, int(raw.get("grid_rows", 8))),
                    "theme": str(raw.get("theme") or "dark"),
                    "background": str(raw.get("background") or "#0f172a"),
                    "created_at": str(
                        raw.get("created_at")
                        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    ),
                }
            except Exception as exc:
                logger.warning("Malformed _mix.json in %s (%s); regenerating defaults.", mix_dir, exc)
                meta = self._default_mix_metadata(title=default_title, order=default_order)
                self._write_json(mix_file, meta)

        return {
            "slug": mix_dir.name,
            **meta,
        }

    def list_mixes(self) -> list[dict[str, Any]]:
        """REQ-MIX-001: Return all webmixes sorted ascending by order, then slug."""
        self.ensure_initialized()
        mixes: list[dict[str, Any]] = []
        subdirs = sorted(
            [p for p in self.root_dir.iterdir() if self._is_valid_mix_dir(p)],
            key=lambda p: p.name,
        )
        for idx, mix_dir in enumerate(subdirs):
            meta = self._load_or_create_mix_meta(mix_dir, default_order=idx)
            mixes.append(meta)
        mixes.sort(key=lambda m: (m["order"], m["slug"]))
        return mixes

    def get_mix(self, mix_slug: str) -> dict[str, Any] | None:
        """Return webmix metadata and its tiles for a given mix_slug."""
        mix_dir = (self.root_dir / mix_slug).resolve()
        if mix_dir.parent != self.root_dir or not self._is_valid_mix_dir(mix_dir):
            return None
        meta = self._load_or_create_mix_meta(mix_dir, default_order=0)
        tiles = self.list_tiles(mix_slug)
        return {
            **meta,
            "tiles": tiles,
        }

    def list_tiles(self, mix_slug: str) -> list[dict[str, Any]]:
        """REQ-FS-007, REQ-FS-008, REQ-FS-011: Scan and return valid tiles in a webmix."""
        mix_dir = (self.root_dir / mix_slug).resolve()
        if mix_dir.parent != self.root_dir or not mix_dir.is_dir():
            return []

        tiles: list[dict[str, Any]] = []
        for file_path in sorted(mix_dir.glob("*.json"), key=lambda p: p.name):
            if file_path.name.startswith("_") or file_path.name.startswith("."):
                continue
            tile = self._read_tile_file(file_path)
            if tile is not None:
                tiles.append(tile)
        return tiles

    def _read_tile_file(self, file_path: Path) -> dict[str, Any] | None:
        """Read and validate a single tile JSON file. Skip & warn on malformed data."""
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Tile JSON must be an object")

            x = raw.get("x")
            y = raw.get("y")
            if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
                raise ValueError(f"Invalid coordinates x={x!r}, y={y!r}")
            if x < 0 or y < 0:
                raise ValueError(f"Negative coordinates x={x}, y={y}")

            w = int(raw.get("w", 1))
            h = int(raw.get("h", 1))
            if w < 1 or h < 1:
                raise ValueError(f"Invalid dimensions w={w}, h={h}")

            tile_id = file_path.stem
            name = str(raw.get("name") or tile_id)
            url = str(raw.get("url") or "#")
            bg_color = str(raw.get("bg_color") or "#1e293b")
            text_color = str(raw.get("text_color") or "#ffffff")
            show_label = bool(raw.get("show_label", True))

            icon_val = raw.get("icon")
            icon_url = raw.get("icon_url")
            icon_type = raw.get("icon_type")
            if not icon_type:
                if icon_url:
                    icon_type = "cached" if str(icon_url).startswith("/icons/") else "external"
                elif icon_val:
                    icon_type = "lucide"
                else:
                    icon_type = "monogram"

            # Normalize lucide icon prefix if present
            lucide_icon = str(icon_val).replace("lucide:", "") if icon_val else None
            monogram = str(raw.get("monogram") or generate_monogram(name, url))[:4]
            raw_tags = raw.get("tags", [])
            tags = [str(t).strip() for t in raw_tags if str(t).strip()] if isinstance(raw_tags, list) else []
            target = str(raw.get("target") or "_blank")
            if target not in ("_blank", "_self"):
                target = "_blank"

            return {
                "id": tile_id,
                "name": name,
                "url": url,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "bg_color": bg_color,
                "text_color": text_color,
                "show_label": show_label,
                "icon_type": icon_type,
                "icon": lucide_icon,
                "icon_url": icon_url,
                "monogram": monogram,
                "tags": tags,
                "target": target,
            }
        except Exception as exc:
            logger.warning("Skipping malformed tile file %s: %s", file_path, exc)
            return None

    def _serialize_tile_payload(self, tile: dict[str, Any]) -> dict[str, Any]:
        """Prepare clean ordered dictionary for writing a tile .json file."""
        icon_val = tile.get("icon")
        if icon_val and not str(icon_val).startswith("lucide:"):
            icon_formatted: str | None = f"lucide:{icon_val}"
        else:
            icon_formatted = icon_val or None

        return {
            "id": tile["id"],
            "name": tile["name"],
            "url": tile["url"],
            "x": int(tile["x"]),
            "y": int(tile["y"]),
            "w": int(tile.get("w", 1)),
            "h": int(tile.get("h", 1)),
            "bg_color": tile.get("bg_color", "#1e293b"),
            "text_color": tile.get("text_color", "#ffffff"),
            "show_label": bool(tile.get("show_label", True)),
            "icon_type": tile.get("icon_type", "monogram"),
            "icon": icon_formatted,
            "icon_url": tile.get("icon_url") or None,
            "monogram": (tile.get("monogram") or generate_monogram(tile["name"], tile["url"]))[:4],
            "tags": list(tile.get("tags", [])),
            "target": tile.get("target", "_blank"),
        }

    def get_tile(self, mix_slug: str, tile_id: str) -> dict[str, Any] | None:
        mix_dir = (self.root_dir / mix_slug).resolve()
        if mix_dir.parent != self.root_dir or not mix_dir.is_dir():
            return None
        file_path = (mix_dir / f"{tile_id}.json").resolve()
        if file_path.parent != mix_dir or not file_path.exists():
            return None
        return self._read_tile_file(file_path)

    def create_mix(
        self,
        title: str,
        slug: str | None = None,
        grid_cols: int = 12,
        grid_rows: int = 8,
        theme: str = "dark",
        background: str = "#0f172a",
    ) -> dict[str, Any]:
        """REQ-MIX-003 & REQ-MIX-004: Create a new webmix directory and _mix.json."""
        title = (title or "").strip() or "New Webmix"
        explicit_slug = bool(slug and slug.strip())
        base_slug = slugify(slug if explicit_slug else title, fallback="mix")

        target_slug = base_slug
        mix_dir = self.root_dir / target_slug
        if mix_dir.exists():
            if explicit_slug:
                raise FileExistsError(f"Webmix '{target_slug}' already exists.")
            counter = 2
            while (self.root_dir / f"{base_slug}-{counter}").exists():
                counter += 1
            target_slug = f"{base_slug}-{counter}"
            mix_dir = self.root_dir / target_slug

        existing = self.list_mixes()
        next_order = (max((m["order"] for m in existing), default=-1) + 1) if existing else 0

        mix_dir.mkdir(parents=True, exist_ok=True)
        meta = self._default_mix_metadata(
            title=title,
            order=next_order,
            grid_cols=max(1, min(30, int(grid_cols))),
            grid_rows=max(1, min(30, int(grid_rows))),
            theme=theme if theme in ("dark", "light") else "dark",
            background=background or "#0f172a",
        )
        self._write_json(mix_dir / "_mix.json", meta)
        return self.get_mix(target_slug)  # type: ignore[return-value]

    def update_mix(
        self,
        mix_slug: str,
        title: str | None = None,
        grid_cols: int | None = None,
        grid_rows: int | None = None,
        theme: str | None = None,
        background: str | None = None,
        relocate_out_of_bounds: bool = False,
    ) -> dict[str, Any]:
        """REQ-MIX-006 & REQ-MIX-007: Update webmix metadata and handle out-of-bounds tiles."""
        mix = self.get_mix(mix_slug)
        if not mix:
            raise FileNotFoundError(f"Webmix '{mix_slug}' not found.")

        new_cols = max(1, min(30, int(grid_cols))) if grid_cols is not None else mix["grid_cols"]
        new_rows = max(1, min(30, int(grid_rows))) if grid_rows is not None else mix["grid_rows"]

        tiles = mix["tiles"]
        out_of_bounds = [t for t in tiles if t["x"] >= new_cols or t["y"] >= new_rows]
        if out_of_bounds:
            if not relocate_out_of_bounds:
                raise OutOfBoundsError(
                    f"{len(out_of_bounds)} tile(s) lie outside the new {new_cols}×{new_rows} grid bounds.",
                    affected_tiles=out_of_bounds,
                )
            if len(tiles) > new_cols * new_rows:
                raise BoardFullError(
                    f"Cannot shrink grid to {new_cols}×{new_rows} ({new_cols * new_rows} slots): "
                    f"webmix contains {len(tiles)} tiles."
                )
            # Relocate out-of-bounds tiles to nearest free slots within (new_cols, new_rows)
            occupied = {
                (t["x"], t["y"])
                for t in tiles
                if t["x"] < new_cols and t["y"] < new_rows
            }
            mix_dir = self.root_dir / mix_slug
            for ob_tile in out_of_bounds:
                target_x = min(ob_tile["x"], new_cols - 1)
                target_y = min(ob_tile["y"], new_rows - 1)
                free_coord = self._find_nearest_free_slot(
                    occupied, new_cols, new_rows, start_x=target_x, start_y=target_y
                )
                if free_coord is None:
                    raise BoardFullError("No free slots available to relocate out-of-bounds tiles.")
                ob_tile["x"], ob_tile["y"] = free_coord
                occupied.add(free_coord)
                self._write_json(mix_dir / f"{ob_tile['id']}.json", self._serialize_tile_payload(ob_tile))

        meta = {
            "title": (title.strip() if title and title.strip() else mix["title"]),
            "order": mix["order"],
            "grid_cols": new_cols,
            "grid_rows": new_rows,
            "theme": theme if theme in ("dark", "light") else mix["theme"],
            "background": (background.strip() if background and background.strip() else mix["background"]),
            "created_at": mix["created_at"],
        }
        self._write_json(self.root_dir / mix_slug / "_mix.json", meta)
        return self.get_mix(mix_slug)  # type: ignore[return-value]

    def reorder_mixes(self, ordered_slugs: list[str]) -> list[dict[str, Any]]:
        """REQ-MIX-005: Persist new tab order across _mix.json files."""
        all_mixes = {m["slug"]: m for m in self.list_mixes()}
        seen: set[str] = set()
        final_order: list[str] = []
        for slug in ordered_slugs:
            if slug in all_mixes and slug not in seen:
                final_order.append(slug)
                seen.add(slug)
        for slug in all_mixes:
            if slug not in seen:
                final_order.append(slug)

        for idx, slug in enumerate(final_order):
            m = all_mixes[slug]
            if m["order"] != idx:
                meta = {
                    "title": m["title"],
                    "order": idx,
                    "grid_cols": m["grid_cols"],
                    "grid_rows": m["grid_rows"],
                    "theme": m["theme"],
                    "background": m["background"],
                    "created_at": m["created_at"],
                }
                self._write_json(self.root_dir / slug / "_mix.json", meta)

        return self.list_mixes()

    def delete_mix(self, mix_slug: str) -> None:
        """REQ-MIX-008: Delete webmix directory and its tiles while preserving _icons/."""
        mix_dir = (self.root_dir / mix_slug).resolve()
        if mix_dir.parent != self.root_dir or not self._is_valid_mix_dir(mix_dir):
            raise FileNotFoundError(f"Webmix '{mix_slug}' not found.")
        self.mark_internal_write()
        shutil.rmtree(mix_dir)
        self.ensure_initialized()

    @staticmethod
    def _find_nearest_free_slot(
        occupied: set[tuple[int, int]],
        grid_cols: int,
        grid_rows: int,
        start_x: int = 0,
        start_y: int = 0,
    ) -> tuple[int, int] | None:
        """Find the nearest unoccupied (x, y) slot by Euclidean distance, then row-major order."""
        if (start_x, start_y) not in occupied and 0 <= start_x < grid_cols and 0 <= start_y < grid_rows:
            return (start_x, start_y)
        candidates: list[tuple[float, int, int]] = []
        for y in range(grid_rows):
            for x in range(grid_cols):
                if (x, y) not in occupied:
                    dist = math.hypot(x - start_x, y - start_y)
                    candidates.append((dist, y, x))
        if not candidates:
            return None
        candidates.sort()
        _, best_y, best_x = candidates[0]
        return (best_x, best_y)

    def _unique_tile_id(self, mix_dir: Path, base_slug: str) -> str:
        """REQ-TILE-004 & REQ-TILE-005: Generate unique slugified filename stem in mix_dir."""
        slug = slugify(base_slug, fallback="tile")
        if not (mix_dir / f"{slug}.json").exists():
            return slug
        counter = 2
        while (mix_dir / f"{slug}-{counter}.json").exists():
            counter += 1
        return f"{slug}-{counter}"

    def create_tile(self, mix_slug: str, data: dict[str, Any]) -> dict[str, Any]:
        """REQ-TILE-004 & REQ-TILE-005: Create a new tile JSON file at (x, y)."""
        mix = self.get_mix(mix_slug)
        if not mix:
            raise FileNotFoundError(f"Webmix '{mix_slug}' not found.")

        mix_dir = self.root_dir / mix_slug
        occupied = {(t["x"], t["y"]): t for t in mix["tiles"]}

        x = data.get("x")
        y = data.get("y")
        if x is None or y is None:
            free = self._find_nearest_free_slot(
                set(occupied.keys()), mix["grid_cols"], mix["grid_rows"], 0, 0
            )
            if free is None:
                raise BoardFullError("This webmix grid is completely full.")
            x, y = free
        else:
            x, y = int(x), int(y)
            if not (0 <= x < mix["grid_cols"] and 0 <= y < mix["grid_rows"]):
                raise OutOfBoundsError(
                    f"Coordinates ({x}, {y}) are outside grid bounds ({mix['grid_cols']}×{mix['grid_rows']})."
                )
            if (x, y) in occupied:
                free = self._find_nearest_free_slot(
                    set(occupied.keys()), mix["grid_cols"], mix["grid_rows"], x, y
                )
                if free is None:
                    raise BoardFullError("This webmix grid is completely full.")
                x, y = free

        name = str(data.get("name") or "").strip() or "Bookmark"
        url = str(data.get("url") or "").strip() or "https://example.com"
        desired_slug = str(data.get("slug") or "").strip() or name
        tile_id = self._unique_tile_id(mix_dir, desired_slug)

        tile_dict = {
            "id": tile_id,
            "name": name,
            "url": url,
            "x": x,
            "y": y,
            "w": int(data.get("w", 1)),
            "h": int(data.get("h", 1)),
            "bg_color": str(data.get("bg_color") or "#1e293b"),
            "text_color": str(data.get("text_color") or "#ffffff"),
            "show_label": bool(data.get("show_label", True)),
            "icon_type": str(data.get("icon_type") or "monogram"),
            "icon": data.get("icon") or None,
            "icon_url": data.get("icon_url") or None,
            "monogram": (str(data.get("monogram") or "").strip() or generate_monogram(name, url))[:4],
            "tags": [str(t).strip() for t in data.get("tags", []) if str(t).strip()],
            "target": data.get("target") if data.get("target") in ("_blank", "_self") else "_blank",
        }
        payload = self._serialize_tile_payload(tile_dict)
        self._write_json(mix_dir / f"{tile_id}.json", payload)
        return self.get_tile(mix_slug, tile_id)  # type: ignore[return-value]

    def update_tile(self, mix_slug: str, tile_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """REQ-TILE-007: Update an existing tile (and optionally rename its slug)."""
        mix = self.get_mix(mix_slug)
        if not mix:
            raise FileNotFoundError(f"Webmix '{mix_slug}' not found.")
        existing = self.get_tile(mix_slug, tile_id)
        if not existing:
            raise FileNotFoundError(f"Tile '{tile_id}' not found in '{mix_slug}'.")

        mix_dir = self.root_dir / mix_slug
        old_file = mix_dir / f"{tile_id}.json"

        name = str(data.get("name") if "name" in data else existing["name"]).strip() or existing["name"]
        url = str(data.get("url") if "url" in data else existing["url"]).strip() or existing["url"]
        x = int(data["x"]) if "x" in data and data["x"] is not None else existing["x"]
        y = int(data["y"]) if "y" in data and data["y"] is not None else existing["y"]

        if not (0 <= x < mix["grid_cols"] and 0 <= y < mix["grid_rows"]):
            raise OutOfBoundsError(
                f"Coordinates ({x}, {y}) are outside grid bounds ({mix['grid_cols']}×{mix['grid_rows']})."
            )

        new_slug_req = data.get("new_slug")
        target_id = tile_id
        if new_slug_req and slugify(str(new_slug_req)) != tile_id:
            target_id = self._unique_tile_id(mix_dir, str(new_slug_req))

        updated = {
            "id": target_id,
            "name": name,
            "url": url,
            "x": x,
            "y": y,
            "w": int(data.get("w", existing["w"])),
            "h": int(data.get("h", existing["h"])),
            "bg_color": str(data.get("bg_color") or existing["bg_color"]),
            "text_color": str(data.get("text_color") or existing["text_color"]),
            "show_label": bool(data["show_label"]) if "show_label" in data else existing["show_label"],
            "icon_type": str(data.get("icon_type") or existing["icon_type"]),
            "icon": data.get("icon") if "icon" in data else existing["icon"],
            "icon_url": data.get("icon_url") if "icon_url" in data else existing["icon_url"],
            "monogram": (
                str(data.get("monogram") or "").strip()
                if "monogram" in data and data.get("monogram")
                else generate_monogram(name, url)
            )[:4],
            "tags": (
                [str(t).strip() for t in data["tags"] if str(t).strip()]
                if "tags" in data and isinstance(data["tags"], list)
                else existing["tags"]
            ),
            "target": (
                data["target"]
                if data.get("target") in ("_blank", "_self")
                else existing["target"]
            ),
        }

        payload = self._serialize_tile_payload(updated)
        new_file = mix_dir / f"{target_id}.json"
        self._write_json(new_file, payload)
        if target_id != tile_id and old_file.exists():
            old_file.unlink()
        return self.get_tile(mix_slug, target_id)  # type: ignore[return-value]

    def move_tile(self, mix_slug: str, tile_id: str, target_x: int, target_y: int) -> dict[str, Any]:
        """REQ-GRID-004, REQ-GRID-005, REQ-GRID-006: Move tile to (x, y) or swap with occupying tile."""
        mix = self.get_mix(mix_slug)
        if not mix:
            raise FileNotFoundError(f"Webmix '{mix_slug}' not found.")

        target_x = int(target_x)
        target_y = int(target_y)
        if not (0 <= target_x < mix["grid_cols"] and 0 <= target_y < mix["grid_rows"]):
            raise OutOfBoundsError(
                f"Target slot ({target_x}, {target_y}) is outside grid bounds ({mix['grid_cols']}×{mix['grid_rows']})."
            )

        tiles_by_id = {t["id"]: t for t in mix["tiles"]}
        if tile_id not in tiles_by_id:
            raise FileNotFoundError(f"Tile '{tile_id}' not found in '{mix_slug}'.")

        moving_tile = tiles_by_id[tile_id]
        old_x, old_y = moving_tile["x"], moving_tile["y"]
        if (old_x, old_y) == (target_x, target_y):
            return {"moved": moving_tile, "swapped": None}

        occupying_tile = next(
            (t for t in mix["tiles"] if t["id"] != tile_id and t["x"] == target_x and t["y"] == target_y),
            None,
        )

        mix_dir = self.root_dir / mix_slug
        moving_tile["x"] = target_x
        moving_tile["y"] = target_y

        if occupying_tile is not None:
            occupying_tile["x"] = old_x
            occupying_tile["y"] = old_y
            self._write_json(
                mix_dir / f"{occupying_tile['id']}.json",
                self._serialize_tile_payload(occupying_tile),
            )

        self._write_json(
            mix_dir / f"{moving_tile['id']}.json",
            self._serialize_tile_payload(moving_tile),
        )
        return {"moved": moving_tile, "swapped": occupying_tile}

    def duplicate_tile(self, mix_slug: str, tile_id: str) -> dict[str, Any]:
        """REQ-TILE-008 & REQ-TILE-009: Duplicate a tile into the nearest unoccupied cell."""
        mix = self.get_mix(mix_slug)
        if not mix:
            raise FileNotFoundError(f"Webmix '{mix_slug}' not found.")
        source = self.get_tile(mix_slug, tile_id)
        if not source:
            raise FileNotFoundError(f"Tile '{tile_id}' not found in '{mix_slug}'.")

        occupied = {(t["x"], t["y"]) for t in mix["tiles"]}
        free = self._find_nearest_free_slot(
            occupied, mix["grid_cols"], mix["grid_rows"], start_x=source["x"], start_y=source["y"]
        )
        if free is None:
            raise BoardFullError("Cannot duplicate tile: all slots in this webmix are occupied.")

        clone_data = {
            **source,
            "x": free[0],
            "y": free[1],
            "slug": source["id"],
        }
        return self.create_tile(mix_slug, clone_data)

    def transfer_tile(self, source_mix_slug: str, tile_id: str, target_mix_slug: str) -> dict[str, Any]:
        """REQ-TILE-010: Move a tile .json file from source_mix_slug to target_mix_slug."""
        if source_mix_slug == target_mix_slug:
            tile = self.get_tile(source_mix_slug, tile_id)
            if not tile:
                raise FileNotFoundError(f"Tile '{tile_id}' not found.")
            return tile

        source_tile = self.get_tile(source_mix_slug, tile_id)
        if not source_tile:
            raise FileNotFoundError(f"Tile '{tile_id}' not found in '{source_mix_slug}'.")

        target_mix = self.get_mix(target_mix_slug)
        if not target_mix:
            raise FileNotFoundError(f"Destination webmix '{target_mix_slug}' not found.")

        occupied = {(t["x"], t["y"]) for t in target_mix["tiles"]}
        if len(occupied) >= target_mix["grid_cols"] * target_mix["grid_rows"]:
            raise BoardFullError(f"Destination webmix '{target_mix['title']}' is completely full.")

        pref_x, pref_y = source_tile["x"], source_tile["y"]
        if (
            0 <= pref_x < target_mix["grid_cols"]
            and 0 <= pref_y < target_mix["grid_rows"]
            and (pref_x, pref_y) not in occupied
        ):
            dest_x, dest_y = pref_x, pref_y
        else:
            # First available unoccupied coordinate in destination webmix (row-major)
            free = self._find_nearest_free_slot(
                occupied, target_mix["grid_cols"], target_mix["grid_rows"], start_x=0, start_y=0
            )
            if free is None:
                raise BoardFullError(f"Destination webmix '{target_mix['title']}' is completely full.")
            dest_x, dest_y = free

        target_dir = self.root_dir / target_mix_slug
        new_id = self._unique_tile_id(target_dir, source_tile["id"])
        moved_tile = {
            **source_tile,
            "id": new_id,
            "x": dest_x,
            "y": dest_y,
        }
        self._write_json(target_dir / f"{new_id}.json", self._serialize_tile_payload(moved_tile))
        old_path = self.root_dir / source_mix_slug / f"{tile_id}.json"
        if old_path.exists():
            self.mark_internal_write()
            old_path.unlink()
        return self.get_tile(target_mix_slug, new_id)  # type: ignore[return-value]

    def delete_tile(self, mix_slug: str, tile_id: str) -> None:
        """REQ-TILE-011: Remove {tile_id}.json from the webmix directory."""
        mix_dir = (self.root_dir / mix_slug).resolve()
        if mix_dir.parent != self.root_dir or not mix_dir.is_dir():
            raise FileNotFoundError(f"Webmix '{mix_slug}' not found.")
        file_path = (mix_dir / f"{tile_id}.json").resolve()
        if file_path.parent != mix_dir or not file_path.exists():
            raise FileNotFoundError(f"Tile '{tile_id}' not found in '{mix_slug}'.")
        self.mark_internal_write()
        file_path.unlink()

    def rebuild_search_index(self) -> list[dict[str, Any]]:
        """Build in-memory search index across all webmixes."""
        entries: list[dict[str, Any]] = []
        for mix in self.list_mixes():
            tiles = self.list_tiles(mix["slug"])
            for t in tiles:
                haystack = " ".join(
                    [
                        t["name"],
                        t["url"],
                        " ".join(t.get("tags", [])),
                        mix["title"],
                        mix["slug"],
                    ]
                ).lower()
                entries.append(
                    {
                        "tile_id": t["id"],
                        "name": t["name"],
                        "url": t["url"],
                        "x": t["x"],
                        "y": t["y"],
                        "bg_color": t["bg_color"],
                        "text_color": t["text_color"],
                        "icon_type": t["icon_type"],
                        "icon": t["icon"],
                        "icon_url": t["icon_url"],
                        "monogram": t["monogram"],
                        "tags": t["tags"],
                        "target": t["target"],
                        "mix_slug": mix["slug"],
                        "mix_title": mix["title"],
                        "_haystack": haystack,
                    }
                )
        self._search_cache = entries
        self._cache_dirty = False
        return entries

    def search(self, query: str = "") -> list[dict[str, Any]]:
        """REQ-SRCH-002: Filter in-memory tile index across all webmixes in < 2ms."""
        if self._cache_dirty:
            self.rebuild_search_index()
        q = (query or "").strip().lower()
        if not q:
            return [{k: v for k, v in item.items() if k != "_haystack"} for item in self._search_cache]

        tokens = [tok for tok in q.split() if tok]
        results: list[dict[str, Any]] = []
        for item in self._search_cache:
            if all(tok in item["_haystack"] for tok in tokens):
                results.append({k: v for k, v in item.items() if k != "_haystack"})
        return results
