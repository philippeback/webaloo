from __future__ import annotations

import json
from pathlib import Path

import pytest

from webmiximport.importer import SymbalooImporter, discover_webmixes, import_symbaloo, rgb_to_hex


def test_rgb_to_hex():
    assert rgb_to_hex("rgb(46, 121, 219)") == "#2e79db"
    assert rgb_to_hex("rgba(255, 146, 0, 0.8)") == "#ff9200"
    assert rgb_to_hex("#123456") == "#123456"
    assert rgb_to_hex("blue") == "#2563eb"
    assert rgb_to_hex("orange") == "#f97316"
    assert rgb_to_hex(None, default="#000000") == "#000000"


def test_discover_webmixes_from_sample():
    sample_path = Path("data/webmix/Symbaloo_ Bookmarks & Favorites - The #1 Homepage for Educators.html")
    assert sample_path.is_file()

    mixes = discover_webmixes(str(sample_path))
    assert len(mixes) == 36
    assert mixes[0]["title"] == "High Octane"
    assert mixes[0]["is_active"] is True
    assert "13eP25RWIi" in mixes[0]["url"]
    assert mixes[0]["desktop_id"] == "RGVza3RvcEdRTDoxMDAwMDAzMDAwMDg1Nzky"


def test_import_desktop_data_graphql_schema(tmp_path: Path):
    importer = SymbalooImporter(target_root=tmp_path)
    mock_desktop = {
        "name": "GraphQL Test Mix",
        "width": 10,
        "height": 6,
        "background": {"color": "blue"},
        "smarks": [
            {
                "name": "Search Engine",
                "x": 0,
                "y": 0,
                "width": 1,
                "height": 1,
                "color": "sky",
                "image": None,
                "typed": {"url": "https://duckduckgo.com"},
            },
            {
                "name": "Social",
                "x": 1,
                "y": 0,
                "width": 1,
                "height": 1,
                "color": "orange",
                "image": None,
                "typed": {"url": "https://mastodon.social"},
            },
        ],
    }

    summary = importer.import_desktop_data(mock_desktop)
    assert summary["slug"] == "graphql-test-mix"
    assert summary["title"] == "GraphQL Test Mix"
    assert summary["tiles_count"] == 2
    assert summary["grid_cols"] == 10
    assert summary["grid_rows"] == 6

    mix_dir = tmp_path / "graphql-test-mix"
    assert (mix_dir / "_mix.json").is_file()
    assert (mix_dir / "search-engine.json").is_file()
    assert (mix_dir / "social.json").is_file()

    tile1 = json.loads((mix_dir / "search-engine.json").read_text(encoding="utf-8"))
    assert tile1["bg_color"] == "#0ea5e9"
    assert tile1["url"] == "https://duckduckgo.com"
    assert tile1["icon_type"] == "monogram"


def test_contrast_text_color():
    from webaloo.storage import get_contrast_text_color

    assert get_contrast_text_color("#ffffff") == "#0f172a"
    assert get_contrast_text_color("#f8fafc") == "#0f172a"
    assert get_contrast_text_color("#e2e8f0") == "#0f172a"
    assert get_contrast_text_color("#000000") == "#ffffff"
    assert get_contrast_text_color("#0f172a") == "#ffffff"
    assert get_contrast_text_color("#1e293b") == "#ffffff"
    assert get_contrast_text_color("#2563eb") == "#ffffff"
    assert get_contrast_text_color("#dc2626") == "#ffffff"


def test_import_symbaloo_from_sample(tmp_path: Path):
    sample_path = Path("data/webmix/Symbaloo_ Bookmarks & Favorites - The #1 Homepage for Educators.html")
    summary = import_symbaloo(
        source=str(sample_path),
        target_root=tmp_path,
    )

    assert summary["slug"] == "high-octane"
    assert summary["title"] == "High Octane"
    assert summary["grid_cols"] == 10
    assert summary["grid_rows"] == 6
    assert summary["tiles_count"] == 52
    assert summary["cached_icons"] > 0

    mix_dir = tmp_path / "high-octane"
    assert mix_dir.is_dir()
    assert (mix_dir / "_mix.json").is_file()

    mix_meta = json.loads((mix_dir / "_mix.json").read_text(encoding="utf-8"))
    assert mix_meta["title"] == "High Octane"
    assert mix_meta["grid_cols"] == 10
    assert mix_meta["grid_rows"] == 6

    # Verify unique filenames and duplicate handling
    assert (mix_dir / "myvoo.json").is_file()
    assert (mix_dir / "myvoo-2.json").is_file()

    myvoo_tile = json.loads((mix_dir / "myvoo.json").read_text(encoding="utf-8"))
    assert myvoo_tile["name"] == "myVOO"
    assert myvoo_tile["x"] == 3
    assert myvoo_tile["y"] == 0
    assert myvoo_tile["bg_color"] == "#e02a26"
    assert myvoo_tile["icon_type"] == "cached"
    assert myvoo_tile["icon_url"] == "/icons/ipod.png"

    # Verify icons copied into _icons
    icons_dir = tmp_path / "_icons"
    assert icons_dir.is_dir()
    assert (icons_dir / "ipod.png").is_file()


def test_import_duplicate_slug_increments(tmp_path: Path):
    sample_path = Path("data/webmix/Symbaloo_ Bookmarks & Favorites - The #1 Homepage for Educators.html")
    s1 = import_symbaloo(source=str(sample_path), target_root=tmp_path)
    s2 = import_symbaloo(source=str(sample_path), target_root=tmp_path)

    assert s1["slug"] == "high-octane"
    assert s2["slug"] == "high-octane-2"
    assert (tmp_path / "high-octane").is_dir()
    assert (tmp_path / "high-octane-2").is_dir()
