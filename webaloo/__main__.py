from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from .app import create_app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="webaloo",
        description="Webaloo: Local-first, file-backed visual bookmark manager inspired by Symbaloo.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # import-symbaloo subcommand (REQ-IMP-OPS-001)
    sub_import = subparsers.add_parser(
        "import-symbaloo",
        help="Import a Symbaloo webmix URL or saved HTML export into Webaloo.",
    )
    sub_import.add_argument(
        "source",
        help="Symbaloo webmix URL or HTML export path.",
    )
    sub_import.add_argument(
        "--dir",
        dest="data_dir",
        default=None,
        help="Webaloo root directory (default: ./webmixes).",
    )
    sub_import.add_argument(
        "--list",
        action="store_true",
        help="List discovered webmixes from the page and exit.",
    )
    sub_import.add_argument(
        "--all",
        action="store_true",
        dest="all_mixes",
        help="Import all webmixes discovered from the page navigation tab bar.",
    )
    sub_import.add_argument(
        "--cookies",
        default=None,
        help="Session cookie string or path to cookie file.",
    )
    sub_import.add_argument(
        "--header",
        action="append",
        dest="headers",
        help="Additional HTTP header(s) in 'Key: Value' format.",
    )

    parser.add_argument(
        "--dir",
        dest="data_dir",
        default=None,
        help="Path to the webmixes root directory (overrides WEBALOO_DIR; default: ./webmixes).",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Bind address (overrides WEBALOO_HOST; default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (overrides WEBALOO_PORT; default: 8080).",
    )
    return parser.parse_args(argv)


def resolve_config(args: argparse.Namespace) -> tuple[Path, str, int]:
    """REQ-FS-002 & REQ-FS-003: Resolve root_dir, host, and port with CLI taking precedence over ENV."""
    raw_dir = args.data_dir or os.environ.get("WEBALOO_DIR") or "./webmixes"
    root_dir = Path(raw_dir).resolve()
    host = args.host or os.environ.get("WEBALOO_HOST") or "127.0.0.1"
    port = int(args.port or os.environ.get("WEBALOO_PORT") or 8080)
    return root_dir, host, port


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if getattr(args, "command", None) == "import-symbaloo":
        from webmiximport.__main__ import main as import_main
        sub_argv = [args.source]
        if args.data_dir:
            sub_argv.extend(["--dir", args.data_dir])
        if args.list:
            sub_argv.append("--list")
        if getattr(args, "all_mixes", False):
            sub_argv.append("--all")
        if args.cookies:
            sub_argv.extend(["--cookies", args.cookies])
        if args.headers:
            for h in args.headers:
                sub_argv.extend(["--header", h])
        raise SystemExit(import_main(sub_argv))

    root_dir, host, port = resolve_config(args)
    os.environ["WEBALOO_DIR"] = str(root_dir)
    app = create_app(root_dir=root_dir)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
