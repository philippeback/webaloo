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
    root_dir, host, port = resolve_config(args)
    os.environ["WEBALOO_DIR"] = str(root_dir)
    app = create_app(root_dir=root_dir)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
