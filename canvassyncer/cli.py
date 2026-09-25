"""Command-line interface for Canvas Syncer."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path

from canvassyncer import __version__, auth, config
from canvassyncer.client import CanvasAPIError, CanvasClient
from canvassyncer.sync import Syncer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="canvassyncer",
        description="Sync course files from Canvas LMS to a local directory",
    )
    parser.add_argument(
        "-r",
        "--reconfigure",
        action="store_true",
        help="recreate the config file interactively",
    )
    parser.add_argument(
        "-y",
        action="store_true",
        help="confirm all prompts (skip oversized files, update later versions)",
    )
    parser.add_argument(
        "-p",
        "--path",
        type=Path,
        default=None,
        help="path to the JSON config file",
    )
    parser.add_argument(
        "-c",
        "--connection",
        type=int,
        default=8,
        help="reserved for future parallel downloads (default: 8)",
    )
    parser.add_argument(
        "-x",
        "--proxy",
        default=None,
        help="HTTP(S) proxy URL for API and downloads",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="show debug information",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    sub = parser.add_subparsers(dest="command")
    login = sub.add_parser("login", help="store a Canvas access token in the OS keyring")
    login.add_argument(
        "-p",
        "--path",
        type=Path,
        default=None,
        help="config path (used to resolve the Canvas host)",
    )
    logout = sub.add_parser("logout", help="remove the stored Canvas access token")
    logout.add_argument(
        "-p",
        "--path",
        type=Path,
        default=None,
        help="config path (used to resolve the Canvas host)",
    )
    return parser


def _canvas_url_from_config(path: Path | None) -> str:
    config_path = path or config.default_config_path()
    if config_path.exists():
        try:
            return config.load(config_path).canvas_url
        except Exception:
            pass
    return config.DEFAULT_CANVAS_URL


def cmd_login(args: argparse.Namespace) -> int:
    canvas_url = _canvas_url_from_config(args.path)
    auth.prompt_and_store(canvas_url)
    return 0


def cmd_logout(args: argparse.Namespace) -> int:
    canvas_url = _canvas_url_from_config(args.path)
    if auth.delete_token(canvas_url):
        print(f"Removed token for {auth.host_from_url(canvas_url)}.")
    else:
        print("No token stored in the keyring.")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    config_path = args.path or config.default_config_path()

    if args.reconfigure or not config_path.exists():
        if not config_path.exists():
            print(f"Config file does not exist, creating at {config_path}...")
        existing = None
        if config_path.exists():
            try:
                existing = config.load(config_path)
            except Exception:
                existing = None
        config.prompt_config(existing, config_path)
        if args.reconfigure:
            return 0

    cfg = config.load(config_path)
    token = auth.require_token(cfg.canvas_url)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    with CanvasClient(cfg.canvas_url, token, proxy=args.proxy) as client:
        Syncer(cfg, client, confirm_all=args.y, connections=args.connection).sync()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "login":
            return cmd_login(args)
        if args.command == "logout":
            return cmd_logout(args)
        return cmd_sync(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except CanvasAPIError as exc:
        print(f"Canvas API error: {exc}", file=sys.stderr)
        if getattr(args, "debug", False):
            traceback.print_exc()
        return 1
    except FileNotFoundError as exc:
        print(f"Config not found: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        if getattr(args, "debug", False):
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
