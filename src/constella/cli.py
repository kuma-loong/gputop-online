from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import uvicorn

from . import __version__
from .agent import AgentConfig, run_agent
from .collector import validate_refresh_interval
from .nvml import sample_with_fallback


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="constella")
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

    agent = subparsers.add_parser("agent", help="run a GPU node agent")
    agent.add_argument("--node-id")
    agent.add_argument("--manager-url")
    agent.add_argument("--token-file")
    agent.add_argument("--refresh", type=float)
    agent.add_argument("--process-refresh", type=float)
    agent.add_argument("--state-file", type=Path)

    args = parser.parse_args(argv)

    if args.command == "serve":
        try:
            refresh = validate_refresh_interval(args.refresh)
        except ValueError as exc:
            parser.error(str(exc))
        os.environ["CONSTELLA_REFRESH_SECONDS"] = str(refresh)
        os.environ["CONSTELLA_PROCESS_SECONDS"] = str(args.process_refresh)
        uvicorn.run(
            "constella.app:create_app",
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

    if args.command == "agent":
        try:
            config = AgentConfig.from_env(
                node_id=args.node_id,
                manager_url=args.manager_url,
                token_file=args.token_file,
                refresh_interval=args.refresh,
                process_interval=args.process_refresh,
                state_file=args.state_file,
            )
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        asyncio.run(run_agent(config))
        return

    parser.print_help()
