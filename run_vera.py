#!/usr/bin/env python3
"""
VERA - Personal AI Assistant (Phase 2 Production)
==================================================

Entry point for VERA system.

Usage:
    # Interactive mode
    python run_vera.py

    # Autonomous mode
    python run_vera.py --auto

    # With debug
    python run_vera.py --debug

    # With observability
    VERA_OBSERVABILITY=1 python run_vera.py
"""

import argparse
import asyncio
import importlib
import logging
import os
import sys
from pathlib import Path

# Add src to path
_src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(_src_path))

# === SAFE BOOT (must be first!) ===
# Detects crash loops and recovers before other imports that might fail
from core.foundation.bootloader import safe_boot
PROJECT_ROOT = Path(__file__).parent
BOOTLOADER = safe_boot(PROJECT_ROOT, memory_dir="vera_memory")

# Import VERA core (after safe boot)
from core.runtime.vera import VERA
from core.runtime.config import VERAConfig
from core.runtime.checkpoint import VERACheckpoint
from core.runtime.health import VERAHealthMonitor
from core.services.memory_service import VERAMemoryService
from core.services.observability import VERAObservability
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


def _check_playwright_browsers() -> tuple[bool, str]:
    browsers_path = os.getenv("PLAYWRIGHT_BROWSERS_PATH")
    if browsers_path:
        base = Path(browsers_path).expanduser()
    else:
        base = Path.home() / ".cache" / "ms-playwright"

    if not base.exists():
        return False, f"Browser cache not found at {base}"

    chromium_dirs = [p for p in base.iterdir() if p.is_dir() and p.name.startswith("chromium")]
    if not chromium_dirs:
        return False, f"No Chromium install found under {base}"

    return True, f"Chromium installed ({chromium_dirs[-1].name})"


def run_preflight_checks() -> None:
    preflight = os.getenv("VERA_PREFLIGHT", "0") == "1"
    if not preflight:
        return

    voice_enabled = os.getenv("VERA_VOICE", "0") == "1"
    browser_enabled = os.getenv("VERA_BROWSER", "0") == "1"
    desktop_enabled = os.getenv("VERA_DESKTOP", "0") == "1"
    pdf_enabled = os.getenv("VERA_PDF", "0") == "1"

    print("\n=== VERA Preflight ===")

    ok, err = _check_import("httpx")
    print(f"[{'OK' if ok else 'WARN'}] core:httpx {'' if ok else err}")

    api_key_present = bool(os.getenv("XAI_API_KEY") or os.getenv("API_KEY"))
    print(f"[{'OK' if api_key_present else 'WARN'}] api_key {'set' if api_key_present else 'missing'}")

    if voice_enabled:
        ok, err = _check_import("websockets")
        print(f"[{'OK' if ok else 'WARN'}] voice:websockets {'' if ok else err}")
        try:
            from voice.agent import get_available_backend, AudioBackend
            backend = get_available_backend()
            backend_ok = backend != AudioBackend.NONE
            detail = f"backend={backend.value}" if backend_ok else "no audio backend available"
            print(f"[{'OK' if backend_ok else 'WARN'}] voice:audio {detail}")
        except Exception as exc:
            print(f"[WARN] voice:audio {exc}")
    else:
        print("[INFO] voice disabled (VERA_VOICE=1 to enable)")

    if browser_enabled:
        ok, err = _check_import("playwright")
        print(f"[{'OK' if ok else 'WARN'}] browser:playwright {'' if ok else err}")
        if ok:
            ok_browsers, detail = _check_playwright_browsers()
            print(f"[{'OK' if ok_browsers else 'WARN'}] browser:chromium {detail}")
    else:
        print("[INFO] browser disabled (VERA_BROWSER=1 to enable)")

    if desktop_enabled:
        ok, err = _check_import("pyautogui")
        display = os.getenv("DISPLAY")
        ok_display = bool(display)
        print(f"[{'OK' if ok else 'WARN'}] desktop:pyautogui {'' if ok else err}")
        print(f"[{'OK' if ok_display else 'WARN'}] desktop:display {display or 'DISPLAY not set'}")
    else:
        print("[INFO] desktop disabled (VERA_DESKTOP=1 to enable)")

    if pdf_enabled:
        ok, err = _check_import("aiohttp")
        print(f"[{'OK' if ok else 'WARN'}] pdf:aiohttp {'' if ok else err}")
    else:
        print("[INFO] pdf disabled (VERA_PDF=1 to enable)")

    print("=== End Preflight ===\n")


async def main():
    """Main entry point"""
    # Parse arguments
    parser = argparse.ArgumentParser(
        description="VERA - Personal AI Assistant (Phase 2 Production)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_vera.py                  # Interactive mode
  python run_vera.py --auto           # Autonomous mode
  python run_vera.py --debug          # Debug mode
  VERA_OBSERVABILITY=1 python run_vera.py  # With observability

Environment Variables:
  VERA_DEBUG=1                  Enable debug logging
  VERA_OBSERVABILITY=1          Enable observability
  VERA_DRY_RUN=1               Dry-run mode
  VERA_FAULT_TOLERANCE=1       Enable fault tolerance (default)
  VERA_MAX_TOOL_CONCURRENCY=N  Max concurrent tools (default: 10)

For more configuration options, see src/core/runtime/config.py
        """
    )
    parser.add_argument("--auto", action="store_true", help="Run in autonomous mode")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--dev", action="store_true", help="Enable max logging and preflight checks")
    parser.add_argument("--logging", action="store_true", help="Enable max logging and preflight checks")
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

    args = parser.parse_args()

    if args.memory_footprint_mb is not None:
        if args.memory_footprint_mb < 0:
            parser.error("--memory-footprint-mb must be >= 0")
        os.environ["VERA_MEMORY_MAX_FOOTPRINT_MB"] = f"{args.memory_footprint_mb:g}"
    elif not os.getenv("VERA_MEMORY_MAX_FOOTPRINT_MB", "").strip():
        os.environ["VERA_MEMORY_MAX_FOOTPRINT_MB"] = "1024"

    if args.dev or args.logging:
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
                logging.FileHandler(log_file)
            ],
        )
        logging.getLogger("httpx").setLevel(logging.DEBUG)
        logging.getLogger("websockets").setLevel(logging.DEBUG)

    apply_runtime_settings_from_genome()
    run_preflight_checks()

    # Create configuration
    config = VERAConfig().from_args(args)

    # Create VERA instance with bootloader reference
    vera = VERA(config, bootloader=BOOTLOADER)

    # Start VERA
    await vera.start()

    try:
        # Run appropriate mode
        if config.autonomous:
            await vera.run_autonomous()
        else:
            await vera.run_interactive()

    finally:
        # Cleanup
        await vera.stop()
        # Record clean shutdown for bootloader
        BOOTLOADER.record_clean_shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        BOOTLOADER.record_clean_shutdown()
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        # Don't record clean shutdown - this was a crash
        sys.exit(1)
