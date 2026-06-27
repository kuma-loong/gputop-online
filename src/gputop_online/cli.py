from __future__ import annotations

import argparse
import json
import os
import sys

import uvicorn

from . import __version__
from .nvml import sample_with_fallback


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gputop-online")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="run the web service")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--refresh", type=float, default=1.0)
    serve.add_argument("--process-refresh", type=float, default=3.0)
    serve.add_argument("--log-level", default="info")

    probe = subparsers.add_parser("probe", help="print one JSON GPU snapshot")
    probe.add_argument("--pretty", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "serve":
        os.environ["GPUTOP_REFRESH_SECONDS"] = str(args.refresh)
        os.environ["GPUTOP_PROCESS_SECONDS"] = str(args.process_refresh)
        uvicorn.run(
            "gputop_online.app:create_app",
            host=args.host,
            port=args.port,
            factory=True,
            log_level=args.log_level,
            lifespan="on",
        )
        return

    if args.command == "probe":
        snapshot = sample_with_fallback()
        json.dump(
            snapshot.to_dict(),
            sys.stdout,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
        )
        sys.stdout.write("\n")
        return

    parser.print_help()
