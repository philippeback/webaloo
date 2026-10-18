from __future__ import annotations

import asyncio
import json
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .icons import ALLOWED_ICON_EXTENSIONS, fetch_site_icon_and_metadata, sanitize_icon_filename
from .storage import BoardFullError, OutOfBoundsError, Storage
from .watcher import FileWatcherBroadcaster

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

LUCIDE_ICON_CATALOG = [
    "globe", "bookmark", "star", "heart", "zap", "flame", "compass", "search",
    "home", "terminal", "code", "cpu", "database", "server", "hard-drive", "cloud",
    "candlestick-chart", "line-chart", "bar-chart-3", "pie-chart", "trending-up", "wallet", "coins", "dollar-sign",
    "headphones", "music", "mic", "radio", "Sliders", "volume-2", "disc", "film",
    "youtube", "github", "gitlab", "figma", "slack", "trello", "chrome", "mail",
    "message-square", "send", "bell", "calendar", "clock", "folder", "file-text", "book-open",
    "graduation-cap", "briefcase", "shopping-cart", "credit-card", "package", "truck", "map-pin", "navigation",
    "camera", "image", "palette", "pen-tool", "layers", "layout-grid", "monitor", "smartphone",
    "tv", "gamepad-2", "Coffee", "utensils", "Dumbbell", "activity", "shield", "lock",
    "key", "settings", "wrench", "sliders-horizontal", "Sparkles", "bot", "brain", "rocket",
]


def _build_grid_matrix(mix: dict[str, Any]) -> list[list[dict[str, Any] | None]]:
    """Construct a 2D [row][col] matrix of tiles (or None for empty slots)."""
    cols = mix["grid_cols"]
    rows = mix["grid_rows"]
    grid: list[list[dict[str, Any] | None]] = [[None for _ in range(cols)] for _ in range(rows)]
    for tile in mix.get("tiles", []):
        x, y = tile["x"], tile["y"]
        if 0 <= x < cols and 0 <= y < rows:
            grid[y][x] = tile
    return grid


async def _parse_body(request: Request) -> dict[str, Any]:
    """Parse request payload from either JSON or form-encoded data."""
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            return await request.json()
        except Exception:
            return {}
    try:
        form = await request.form()
        data: dict[str, Any] = {}
        for k, v in form.multi_items():
            if k in data:
                if isinstance(data[k], list):
                    data[k].append(v)
                else:
                    data[k] = [data[k], v]
            else:
                data[k] = v
        return data
    except Exception:
        try:
            return await request.json()
        except Exception:
            return {}


def _normalize_tile_input(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize form or JSON fields into tile schema types."""
    data = dict(raw)
    if "tags" in data and isinstance(data["tags"], str):
        data["tags"] = [t.strip() for t in data["tags"].split(",") if t.strip()]
    if "show_label" in data and not isinstance(data["show_label"], bool):
        val = str(data["show_label"]).strip().lower()
        data["show_label"] = val in ("true", "1", "on", "yes")
    for int_field in ("x", "y", "w", "h"):
        if int_field in data and data[int_field] not in (None, ""):
            data[int_field] = int(data[int_field])
    return data


def create_app(root_dir: str | Path | None = None, enable_watcher: bool = True) -> FastAPI:
    storage = Storage(root_dir=root_dir)
    watcher = FileWatcherBroadcaster(storage=storage)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        storage.rebuild_search_index()
        if enable_watcher:
            await watcher.start()
        try:
            yield
        finally:
            if enable_watcher:
                await watcher.stop()

    app = FastAPI(
        title="Webaloo",
        description="Local-first, file-backed visual bookmark manager inspired by Symbaloo",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.storage = storage
    app.state.watcher = watcher
    app.state.templates = templates

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        mixes = storage.list_mixes()
        first_slug = mixes[0]["slug"]
        mix = storage.get_mix(first_slug)
        if not mix:
            raise HTTPException(status_code=404, detail="Default webmix not found")
        grid = _build_grid_matrix(mix)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "mixes": mixes,
                "active_mix": mix,
                "grid": grid,
                "lucide_icons": [i.lower() for i in LUCIDE_ICON_CATALOG],
            },
        )

    @app.get("/mix/{mix_slug}", response_class=HTMLResponse)
    async def view_mix(request: Request, mix_slug: str, highlight: str | None = Query(default=None)):
        mixes = storage.list_mixes()
        mix = storage.get_mix(mix_slug)
        if not mix:
            if mixes:
                return RedirectResponse(url=f"/mix/{mixes[0]['slug']}", status_code=302)
            raise HTTPException(status_code=404, detail=f"Webmix '{mix_slug}' not found")

        grid = _build_grid_matrix(mix)
        is_htmx = request.headers.get("HX-Request", "").lower() == "true"
        template_name = "partials/workspace.html" if is_htmx else "index.html"
        return templates.TemplateResponse(
            request,
            template_name,
            {
                "mixes": mixes,
                "active_mix": mix,
                "grid": grid,
                "highlight_tile": highlight,
                "lucide_icons": [i.lower() for i in LUCIDE_ICON_CATALOG],
            },
        )

    @app.get("/api/mixes")
    async def api_list_mixes():
        return {"mixes": storage.list_mixes()}

    @app.get("/api/mixes/{mix_slug}")
    async def api_get_mix(mix_slug: str):
        mix = storage.get_mix(mix_slug)
        if not mix:
            raise HTTPException(status_code=404, detail=f"Webmix '{mix_slug}' not found")
        return mix

    @app.post("/api/mixes")
    async def api_create_mix(request: Request):
        data = await _parse_body(request)
        title = str(data.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Webmix title is required.")
        slug = str(data.get("slug") or "").strip() or None
        grid_cols = int(data.get("grid_cols") or 12)
        grid_rows = int(data.get("grid_rows") or 8)
        theme = str(data.get("theme") or "dark")
        background = str(data.get("background") or "#0f172a")
        try:
            created = storage.create_mix(
                title=title,
                slug=slug,
                grid_cols=grid_cols,
                grid_rows=grid_rows,
                theme=theme,
                background=background,
            )
            return JSONResponse(status_code=201, content=created)
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.put("/api/mixes/reorder")
    async def api_reorder_mixes(request: Request):
        data = await _parse_body(request)
        order = data.get("order") or data.get("slugs") or []
        if isinstance(order, str):
            order = [s.strip() for s in order.split(",") if s.strip()]
        if not isinstance(order, list):
            raise HTTPException(status_code=400, detail="Expected 'order' array of webmix slugs.")
        updated = storage.reorder_mixes([str(s) for s in order])
        return {"mixes": updated}

    @app.put("/api/mixes/{mix_slug}")
    async def api_update_mix(mix_slug: str, request: Request):
        data = await _parse_body(request)
        relocate_raw = data.get("relocate_out_of_bounds", False)
        relocate = (
            relocate_raw
            if isinstance(relocate_raw, bool)
            else str(relocate_raw).lower() in ("true", "1", "yes", "on")
        )
        try:
            updated = storage.update_mix(
                mix_slug=mix_slug,
                title=data.get("title"),
                grid_cols=int(data["grid_cols"]) if data.get("grid_cols") is not None else None,
                grid_rows=int(data["grid_rows"]) if data.get("grid_rows") is not None else None,
                theme=data.get("theme"),
                background=data.get("background"),
                relocate_out_of_bounds=relocate,
            )
            return updated
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except OutOfBoundsError as exc:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": str(exc),
                    "code": "OUT_OF_BOUNDS_TILES",
                    "affected_tiles": exc.affected_tiles,
                },
            )
        except BoardFullError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.delete("/api/mixes/{mix_slug}")
    async def api_delete_mix(mix_slug: str):
        try:
            storage.delete_mix(mix_slug)
            remaining = storage.list_mixes()
            return {"deleted": mix_slug, "next_mix": remaining[0]["slug"] if remaining else "default"}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.post("/api/mixes/{mix_slug}/tiles")
    async def api_create_tile(mix_slug: str, request: Request):
        raw = await _parse_body(request)
        data = _normalize_tile_input(raw)
        try:
            tile = storage.create_tile(mix_slug, data)
            return JSONResponse(status_code=201, content=tile)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except (OutOfBoundsError, BoardFullError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.put("/api/mixes/{mix_slug}/tiles/{tile_id}")
    async def api_update_tile(mix_slug: str, tile_id: str, request: Request):
        raw = await _parse_body(request)
        data = _normalize_tile_input(raw)
        try:
            tile = storage.update_tile(mix_slug, tile_id, data)
            return tile
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except OutOfBoundsError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.put("/api/mixes/{mix_slug}/tiles/{tile_id}/move")
    async def api_move_tile(mix_slug: str, tile_id: str, request: Request):
        data = await _parse_body(request)
        if "x" not in data or "y" not in data:
            raise HTTPException(status_code=400, detail="Target coordinates 'x' and 'y' are required.")
        try:
            result = storage.move_tile(mix_slug, tile_id, int(data["x"]), int(data["y"]))
            return result
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except (OutOfBoundsError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/mixes/{mix_slug}/tiles/{tile_id}/duplicate")
    async def api_duplicate_tile(mix_slug: str, tile_id: str):
        try:
            cloned = storage.duplicate_tile(mix_slug, tile_id)
            return JSONResponse(status_code=201, content=cloned)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except BoardFullError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/api/mixes/{mix_slug}/tiles/{tile_id}/transfer")
    async def api_transfer_tile(mix_slug: str, tile_id: str, request: Request):
        data = await _parse_body(request)
        target_mix = str(data.get("target_mix") or data.get("destination") or "").strip()
        if not target_mix:
            raise HTTPException(status_code=400, detail="'target_mix' slug is required.")
        try:
            moved = storage.transfer_tile(mix_slug, tile_id, target_mix)
            return moved
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except BoardFullError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.delete("/api/mixes/{mix_slug}/tiles/{tile_id}")
    async def api_delete_tile(mix_slug: str, tile_id: str):
        try:
            storage.delete_tile(mix_slug, tile_id)
            return {"deleted": tile_id, "mix_slug": mix_slug}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.post("/api/icons/fetch")
    async def api_fetch_icon(request: Request):
        data = await _parse_body(request)
        url = str(data.get("url") or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="URL is required.")
        storage.mark_internal_write()
        result = await fetch_site_icon_and_metadata(url=url, icons_dir=storage.icons_dir)
        storage.mark_internal_write()
        return result

    @app.post("/api/icons/upload")
    async def api_upload_icon(file: UploadFile = File(...)):
        if not file.filename:
            raise HTTPException(status_code=400, detail="Filename is required.")
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_ICON_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file extension '{ext}'. Allowed: {sorted(ALLOWED_ICON_EXTENSIONS)}",
            )
        safe_name = sanitize_icon_filename(file.filename)
        storage.icons_dir.mkdir(parents=True, exist_ok=True)
        dest_path = storage.icons_dir / safe_name
        # Avoid overwriting a different uploaded file if same name exists, or overwrite cleanly
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        storage.mark_internal_write()
        dest_path.write_bytes(content)
        return {
            "ok": True,
            "filename": safe_name,
            "icon_type": "cached",
            "icon_url": f"/icons/{safe_name}",
        }

    @app.get("/icons/{filename}")
    async def serve_cached_icon(filename: str):
        safe_path = (storage.icons_dir / filename).resolve()
        if safe_path.parent != storage.icons_dir or not safe_path.is_file():
            raise HTTPException(status_code=404, detail="Icon not found")
        media_type, _ = mimetypes.guess_type(str(safe_path))
        return FileResponse(safe_path, media_type=media_type or "application/octet-stream")

    @app.get("/api/search")
    async def api_search(q: str = Query(default="")):
        results = storage.search(q)
        return {"query": q, "count": len(results), "results": results}

    @app.get("/api/events")
    async def api_events(request: Request, once: bool = Query(default=False)):
        queue = watcher.subscribe()

        async def event_generator():
            try:
                yield f"event: connected\ndata: {json.dumps({'status': 'ok'})}\n\n"
                if once:
                    return
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                        ev = msg.get("event", "reload")
                        payload = json.dumps(msg.get("data", {}))
                        yield f"event: {ev}\ndata: {payload}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                watcher.unsubscribe(queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app
