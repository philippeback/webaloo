from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webaloo.__main__ import parse_args, resolve_config
from webaloo.app import create_app
from webaloo.storage import Storage


def test_req_fs_001_to_004_initialization(tmp_path: Path):
    """REQ-FS-001..004: Root dir creation, _icons/, and default/_mix.json bootstrap."""
    target_root = tmp_path / "custom_webmixes"
    assert not target_root.exists()

    storage = Storage(root_dir=target_root)
    assert target_root.is_dir()
    assert (target_root / "_icons").is_dir()
    assert (target_root / "default" / "_mix.json").is_file()

    mixes = storage.list_mixes()
    assert len(mixes) == 1
    assert mixes[0]["slug"] == "default"
    assert mixes[0]["grid_cols"] == 12
    assert mixes[0]["grid_rows"] == 8


def test_req_fs_003_cli_and_env_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """REQ-FS-003: --dir takes precedence over WEBALOO_DIR environment variable."""
    env_path = tmp_path / "from_env"
    cli_path = tmp_path / "from_cli"
    monkeypatch.setenv("WEBALOO_DIR", str(env_path))

    args_env = parse_args([])
    resolved_dir, _, _ = resolve_config(args_env)
    assert resolved_dir == env_path.resolve()

    args_cli = parse_args(["--dir", str(cli_path), "--port", "9123"])
    resolved_dir_cli, _, port = resolve_config(args_cli)
    assert resolved_dir_cli == cli_path.resolve()
    assert port == 9123


def test_req_fs_005_to_011_scanning_and_resilience(tmp_path: Path):
    """REQ-FS-005..011: Ignore _/. dirs, auto-create missing _mix.json, skip malformed tile JSON."""
    storage = Storage(root_dir=tmp_path)

    # Hidden and underscore directories should be ignored
    (tmp_path / ".git").mkdir()
    (tmp_path / "_private").mkdir()

    # Webmix missing _mix.json -> REQ-FS-010 generates default _mix.json
    uninitialized_mix = tmp_path / "audio-studio"
    uninitialized_mix.mkdir()

    # Valid tile + malformed JSON tile + invalid coordinates tile
    valid_tile = {
        "name": "KVR Audio",
        "url": "https://www.kvraudio.com",
        "x": 2,
        "y": 3,
    }
    (uninitialized_mix / "kvr-audio.json").write_text(json.dumps(valid_tile, indent=2), encoding="utf-8")
    (uninitialized_mix / "corrupt.json").write_text("{not valid json", encoding="utf-8")
    (uninitialized_mix / "bad-coords.json").write_text(
        json.dumps({"name": "Bad", "url": "https://bad.test", "x": "not-an-int", "y": 1}),
        encoding="utf-8",
    )

    mixes = storage.list_mixes()
    slugs = [m["slug"] for m in mixes]
    assert "audio-studio" in slugs
    assert ".git" not in slugs
    assert "_private" not in slugs
    assert (uninitialized_mix / "_mix.json").is_file()

    tiles = storage.list_tiles("audio-studio")
    assert len(tiles) == 1
    assert tiles[0]["id"] == "kvr-audio"
    assert tiles[0]["x"] == 2
    assert tiles[0]["y"] == 3


def test_req_mix_and_grid_and_tile_api_lifecycle(tmp_path: Path):
    """Test full Webmix, Grid move/swap, Tile CRUD, Duplicate, Transfer, Search, and Icons."""
    app = create_app(root_dir=tmp_path, enable_watcher=False)
    client = TestClient(app)

    # 1. GET / renders main shell with default mix
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Webaloo" in resp.text

    # 2. REQ-MIX-003 & REQ-MIX-004: Create webmixes & handle slug collision
    r_mix1 = client.post(
        "/api/mixes",
        json={"title": "Trading & Markets", "grid_cols": 10, "grid_rows": 6, "background": "#090d16"},
    )
    assert r_mix1.status_code == 201
    assert r_mix1.json()["slug"] == "trading-markets"

    # Auto-suffix when creating duplicate title without explicit slug
    r_mix2 = client.post("/api/mixes", json={"title": "Trading & Markets"})
    assert r_mix2.status_code == 201
    assert r_mix2.json()["slug"] == "trading-markets-2"

    # Explicit duplicate slug returns 409 error
    r_mix_dup = client.post("/api/mixes", json={"title": "Other", "slug": "trading-markets"})
    assert r_mix_dup.status_code == 409

    # 3. REQ-MIX-005: Reorder webmixes
    r_reorder = client.put(
        "/api/mixes/reorder",
        json={"order": ["trading-markets", "default", "trading-markets-2"]},
    )
    assert r_reorder.status_code == 200
    assert [m["slug"] for m in r_reorder.json()["mixes"]] == [
        "trading-markets",
        "default",
        "trading-markets-2",
    ]

    # 4. REQ-TILE-004 & REQ-TILE-005: Create tiles & auto-increment colliding filename stems
    t1 = client.post(
        "/api/mixes/trading-markets/tiles",
        json={
            "name": "TradingView",
            "url": "https://www.tradingview.com/chart/",
            "x": 3,
            "y": 2,
            "bg_color": "#131722",
            "text_color": "#ffffff",
            "icon_type": "lucide",
            "icon": "candlestick-chart",
            "tags": ["trading", "charts"],
        },
    )
    assert t1.status_code == 201
    assert t1.json()["id"] == "tradingview"
    assert (tmp_path / "trading-markets" / "tradingview.json").is_file()

    # REQ-FS-009: Verify 2-space indentation on disk
    raw_file = (tmp_path / "trading-markets" / "tradingview.json").read_text(encoding="utf-8")
    assert '  "name": "TradingView"' in raw_file

    # Second tile with same name gets tradingview-2.json
    t2 = client.post(
        "/api/mixes/trading-markets/tiles",
        json={
            "name": "TradingView",
            "url": "http://192.168.1.50:8888",
            "x": 5,
            "y": 4,
            "tags": ["lan", "local"],
        },
    )
    assert t2.status_code == 201
    assert t2.json()["id"] == "tradingview-2"

    # 5. REQ-GRID-004: Move tile to unoccupied slot
    r_move_empty = client.put(
        "/api/mixes/trading-markets/tiles/tradingview/move",
        json={"x": 1, "y": 1},
    )
    assert r_move_empty.status_code == 200
    assert r_move_empty.json()["moved"]["x"] == 1
    assert r_move_empty.json()["moved"]["y"] == 1
    assert r_move_empty.json()["swapped"] is None

    # 6. REQ-GRID-005: Move tile onto occupied slot -> atomic coordinate swap!
    r_move_swap = client.put(
        "/api/mixes/trading-markets/tiles/tradingview/move",
        json={"x": 5, "y": 4},
    )
    assert r_move_swap.status_code == 200
    assert r_move_swap.json()["moved"]["x"] == 5
    assert r_move_swap.json()["moved"]["y"] == 4
    assert r_move_swap.json()["swapped"]["id"] == "tradingview-2"
    assert r_move_swap.json()["swapped"]["x"] == 1
    assert r_move_swap.json()["swapped"]["y"] == 1

    # 7. REQ-GRID-006: Out-of-bounds move fails with 400
    r_move_oob = client.put(
        "/api/mixes/trading-markets/tiles/tradingview/move",
        json={"x": 99, "y": 99},
    )
    assert r_move_oob.status_code == 400

    # 8. REQ-MIX-007: Shrinking webmix below tile at (5, 4) warns with 409 unless relocate_out_of_bounds=True
    r_shrink_warn = client.put(
        "/api/mixes/trading-markets",
        json={"grid_cols": 4, "grid_rows": 4, "relocate_out_of_bounds": False},
    )
    assert r_shrink_warn.status_code == 409
    assert r_shrink_warn.json()["code"] == "OUT_OF_BOUNDS_TILES"

    r_shrink_relocate = client.put(
        "/api/mixes/trading-markets",
        json={"grid_cols": 4, "grid_rows": 4, "relocate_out_of_bounds": True},
    )
    assert r_shrink_relocate.status_code == 200
    for tile in r_shrink_relocate.json()["tiles"]:
        assert 0 <= tile["x"] < 4
        assert 0 <= tile["y"] < 4

    # 9. REQ-TILE-008: Duplicate tile into nearest free slot
    r_dup = client.post("/api/mixes/trading-markets/tiles/tradingview/duplicate")
    assert r_dup.status_code == 201
    assert r_dup.json()["id"] == "tradingview-3"

    # 10. REQ-TILE-010: Transfer tile to another webmix
    r_xfer = client.post(
        "/api/mixes/trading-markets/tiles/tradingview-3/transfer",
        json={"target_mix": "default"},
    )
    assert r_xfer.status_code == 200
    assert (tmp_path / "default" / "tradingview-3.json").is_file()
    assert not (tmp_path / "trading-markets" / "tradingview-3.json").exists()

    # 11. REQ-SRCH-002: Global instant search across all webmixes
    r_search = client.get("/api/search?q=192.168.1.50")
    assert r_search.status_code == 200
    assert r_search.json()["count"] == 1
    assert r_search.json()["results"][0]["tile_id"] == "tradingview-2"

    # 12. REQ-ICON-001 & REQ-ICON-005: Upload custom icon and serve from /icons/{filename}
    svg_bytes = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>'
    r_upload = client.post(
        "/api/icons/upload",
        files={"file": ("My Custom Icon!.svg", io.BytesIO(svg_bytes), "image/svg+xml")},
    )
    assert r_upload.status_code == 200
    icon_url = r_upload.json()["icon_url"]
    assert icon_url == "/icons/my-custom-icon.svg"

    r_icon_get = client.get(icon_url)
    assert r_icon_get.status_code == 200
    assert b"<svg" in r_icon_get.content

    # 13. REQ-ICON-003: Fetch icon fallback on unreachable/offline URL
    r_fetch_fallback = client.post(
        "/api/icons/fetch",
        json={"url": "http://127.0.0.1:59999/offline"},
    )
    assert r_fetch_fallback.status_code == 200
    assert r_fetch_fallback.json()["icon_type"] == "monogram"
    assert r_fetch_fallback.json()["fallback"] is True

    # 14. REQ-TILE-011 & REQ-MIX-008: Delete tile and delete webmix (preserving _icons/)
    r_del_tile = client.delete("/api/mixes/trading-markets/tiles/tradingview")
    assert r_del_tile.status_code == 200
    assert not (tmp_path / "trading-markets" / "tradingview.json").exists()

    r_del_mix = client.delete("/api/mixes/trading-markets-2")
    assert r_del_mix.status_code == 200
    assert not (tmp_path / "trading-markets-2").exists()
    assert (tmp_path / "_icons" / "my-custom-icon.svg").is_file()


def test_req_tile_009_duplicate_on_full_board(tmp_path: Path):
    """REQ-TILE-009: Reject duplication when all grid_cols * grid_rows slots are occupied."""
    app = create_app(root_dir=tmp_path, enable_watcher=False)
    client = TestClient(app)

    client.post("/api/mixes", json={"title": "Tiny", "slug": "tiny", "grid_cols": 1, "grid_rows": 1})
    client.post("/api/mixes/tiny/tiles", json={"name": "OnlyOne", "url": "https://one.test", "x": 0, "y": 0})

    r_dup = client.post("/api/mixes/tiny/tiles/onlyone/duplicate")
    assert r_dup.status_code == 409
    assert "occupied" in r_dup.json()["detail"].lower() or "full" in r_dup.json()["detail"].lower()
