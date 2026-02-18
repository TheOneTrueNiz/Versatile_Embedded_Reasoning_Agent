#!/usr/bin/env python3
"""
Generate VAPID keys for Web Push.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from py_vapid import Vapid01, b64urlencode
    from cryptography.hazmat.primitives import serialization
except ImportError as exc:  # pragma: no cover
    raise SystemExit("py_vapid is required. Install with: pip install pywebpush") from exc


def _to_str(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _encode_public_key(vapid: Vapid01) -> str:
    public_bytes = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    encoded = b64urlencode(public_bytes)
    return encoded.decode("utf-8") if isinstance(encoded, (bytes, bytearray)) else str(encoded)


def _encode_private_key(vapid: Vapid01) -> str:
    private_value = vapid.private_key.private_numbers().private_value
    raw = private_value.to_bytes(32, "big")
    encoded = b64urlencode(raw)
    return encoded.decode("utf-8") if isinstance(encoded, (bytes, bytearray)) else str(encoded)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate VAPID keys")
    parser.add_argument("--out", default="", help="Write JSON to this path (e.g., config/vapid.json)")
    parser.add_argument("--subject", default="mailto:you@example.com", help="VAPID subject")
    parser.add_argument("--env", action="store_true", help="Print export lines")
    args = parser.parse_args()

    vapid = Vapid01()
    vapid.generate_keys()
    public_key = _encode_public_key(vapid)
    private_key = _encode_private_key(vapid)

    payload = {
        "public_key": public_key,
        "private_key": private_key,
        "subject": args.subject,
    }

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print(f"Saved VAPID keys to {path}")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=True))

    if args.env:
        print("\n# Env format")
        print(f'export VAPID_PUBLIC_KEY="{public_key}"')
        print(f'export VAPID_PRIVATE_KEY="{private_key}"')
        print(f'export VAPID_SUBJECT="{args.subject}"')


if __name__ == "__main__":
    main()
