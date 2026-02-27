#!/usr/bin/env python3
"""
VERA API Server Entry Point
===========================

Starts the VERA runtime with an OpenAI-compatible HTTP API + WebSocket stream.
"""

import argparse
import asyncio
import importlib
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sys
import webbrowser
from pathlib import Path

from aiohttp import web

# Add src to path
_src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(_src_path))

# === SAFE BOOT (must be first!) ===
from core.foundation.bootloader import safe_boot
PROJECT_ROOT = Path(__file__).parent
BOOTLOADER = safe_boot(PROJECT_ROOT, memory_dir="vera_memory")

from core.runtime.vera import VERA
from core.runtime.config import VERAConfig
from api.server import create_app
from core.runtime.genome_config import apply_runtime_settings_from_genome
from core.services.dev_secrets import prime_environment_from_keychain


try:
    prime_environment_from_keychain()
except Exception:
    # Keychain integration is best-effort; env vars still work as normal.
    pass


def _check_import(module_name: str) -> tuple[bool, str]:
    try:
        importlib.import_module(module_name)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def run_preflight_checks() -> None:
    preflight = os.getenv("VERA_PREFLIGHT", "0") == "1"
    if not preflight:
        return

    print("\n=== VERA Preflight ===")
    ok, err = _check_import("httpx")
    print(f"[{'OK' if ok else 'WARN'}] core:httpx {'' if ok else err}")

    ok, err = _check_import("aiohttp")
    print(f"[{'OK' if ok else 'WARN'}] api:aiohttp {'' if ok else err}")

    api_key_present = bool(os.getenv("XAI_API_KEY") or os.getenv("API_KEY"))
    print(f"[{'OK' if api_key_present else 'WARN'}] api_key {'set' if api_key_present else 'missing'}")
    print("=== End Preflight ===\n")


async def main() -> None:
    parser = argparse.ArgumentParser(description="VERA API Server")
    parser.add_argument("--host", default=os.getenv("VERA_API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("VERA_API_PORT", "8788")))
    parser.add_argument("--ui-dist", default=os.getenv("VERA_UI_DIST", ""))
    parser.add_argument(
        "--memory-footprint-mb",
        type=float,
        default=None,
        help=(
            "Max persistent memory footprint budget in MB "
            "(sets VERA_MEMORY_MAX_FOOTPRINT_MB, default: 1024). "
            "Set 0 to disable budget checks."
        ),
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--dev", action="store_true", help="Enable max logging and preflight checks")
    parser.add_argument("--logging", action="store_true", help="Enable max logging and preflight checks")
    args = parser.parse_args()

    if args.memory_footprint_mb is not None:
        if args.memory_footprint_mb < 0:
            parser.error("--memory-footprint-mb must be >= 0")
        os.environ["VERA_MEMORY_MAX_FOOTPRINT_MB"] = f"{args.memory_footprint_mb:g}"
    elif not os.getenv("VERA_MEMORY_MAX_FOOTPRINT_MB", "").strip():
        os.environ["VERA_MEMORY_MAX_FOOTPRINT_MB"] = "1024"

    if args.dev or args.logging or args.debug:
        os.environ["VERA_PREFLIGHT"] = "1"
        os.environ["VERA_DEBUG"] = "1"
        os.environ["VERA_OBSERVABILITY"] = "1"
        os.environ["PYTHONASYNCIODEBUG"] = "1"
        os.environ["PYTHONWARNINGS"] = "default"

        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "vera_debug.log"

        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=[
                logging.StreamHandler(),
                RotatingFileHandler(log_file, maxBytes=50 * 1024 * 1024, backupCount=3)
            ],
        )
        logging.getLogger("httpx").setLevel(logging.DEBUG)

    apply_runtime_settings_from_genome()
    run_preflight_checks()

    config = VERAConfig().from_args(args)
    vera = VERA(config, bootloader=BOOTLOADER)
    await vera.start()

    ui_dist = Path(args.ui_dist).expanduser() if args.ui_dist else None
    stop_event = asyncio.Event()
    shutdown_state = {"handled": False}

    app = create_app(vera, ui_dist=ui_dist)
    app["shutdown_event"] = stop_event
    app["shutdown_state"] = shutdown_state
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.port)
    await site.start()

    print(f"[VERA API] Listening on http://{args.host}:{args.port}")
    if ui_dist:
        print(f"[VERA API] Serving UI from {ui_dist}")
        if os.getenv("VERA_OPEN_BROWSER", "0") == "1":
            host = args.host
            if host in {"0.0.0.0", "::"}:
                host = "127.0.0.1"
            url = os.getenv("VERA_OPEN_BROWSER_URL") or f"http://{host}:{args.port}"
            asyncio.create_task(asyncio.to_thread(webbrowser.open, url, new=1))

    loop = asyncio.get_running_loop()

    def _handle_signal(signum, _frame=None) -> None:
        sig_name = signal.Signals(signum).name
        print(f"\n[SIGNAL] Received {sig_name}")
        loop.call_soon_threadsafe(stop_event.set)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        await stop_event.wait()
    finally:
        await runner.cleanup()
        if not shutdown_state.get("handled"):
            await vera.stop()
        BOOTLOADER.record_clean_shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        BOOTLOADER.record_clean_shutdown()
    except Exception as exc:
        print(f"Fatal error: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
