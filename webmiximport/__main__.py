from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .importer import SymbalooImporter, discover_webmixes, import_symbaloo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="webmiximport",
        description="Import Symbaloo webmixes (URL or HTML export) into Webaloo.",
    )
    parser.add_argument(
        "source",
        help="Symbaloo webmix URL (e.g. https://www.symbaloo.com/home/mix/<id>) or path to saved HTML file.",
    )
    parser.add_argument(
        "--dir",
        dest="data_dir",
        default=None,
        help="Path to the Webaloo root directory (overrides WEBALOO_DIR; default: ./webmixes).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all webmixes discovered from the page navigation tab bar and exit.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_mixes",
        help="Import all webmixes discovered from the page navigation tabs (fetches remote mixes via GraphQL).",
    )
    parser.add_argument(
        "--cookies",
        default=None,
        help="Session cookie string (e.g., 'session_id=...; user_id=...') or path to a cookies file.",
    )
    parser.add_argument(
        "--header",
        action="append",
        dest="headers",
        help="Additional HTTP header(s) in 'Key: Value' format (can be specified multiple times).",
    )
    return parser.parse_args if False else parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    raw_dir = args.data_dir or os.environ.get("WEBALOO_DIR") or "./webmixes"
    target_root = Path(raw_dir).resolve()

    importer = SymbalooImporter(
        target_root=target_root,
        cookies=args.cookies,
        custom_headers=args.headers,
    )

    if args.list:
        try:
            mixes = discover_webmixes(args.source, importer=importer)
            print(f"\nDiscovered {len(mixes)} webmix(es) in '{args.source}':\n")
            print(f"{'#':<3} {'Status':<9} {'Title':<30} {'URL'}")
            print("-" * 80)
            for idx, mix in enumerate(mixes, start=1):
                status = "[ACTIVE]" if mix.get("is_active") else ""
                print(f"{idx:<3} {status:<9} {mix['title']:<30} {mix['url']}")
            print()
            return 0
        except Exception as exc:
            print(f"Error listing webmixes: {exc}", file=sys.stderr)
            return 1

    try:
        if args.all_mixes:
            summaries = import_symbaloo(
                source=args.source,
                target_root=target_root,
                cookies=args.cookies,
                custom_headers=args.headers,
                all_mixes=True,
            )
            print(f"\n=== Symbaloo Import Summary (All Webmixes: {len(summaries)}) ===")
            for item in summaries:
                if "error" in item:
                    print(f"- [FAILED] {item.get('title')}: {item.get('error')}")
                else:
                    print(
                        f"- [OK] {item['title']} ({item['slug']}): {item['tiles_count']} tiles, "
                        f"{item['grid_cols']}x{item['grid_rows']} grid -> {item['mix_dir']}"
                    )
            print()
            return 0

        summary = import_symbaloo(
            source=args.source,
            target_root=target_root,
            cookies=args.cookies,
            custom_headers=args.headers,
        )
        print("\n=== Symbaloo Import Summary ===")
        print(f"Target Slug:       {summary['slug']}")
        print(f"Webmix Title:      {summary['title']}")
        print(f"Grid Dimensions:   {summary['grid_cols']} x {summary['grid_rows']}")
        print(f"Total Tiles:       {summary['tiles_count']}")
        print(f"Cached Icons:      {summary['cached_icons']}")
        print(f"Monograms Used:    {summary['monograms']}")
        print(f"Saved Directory:   {summary['mix_dir']}\n")
        return 0
    except Exception as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
