#!/usr/bin/env python3
import argparse
import os
import sys
import webbrowser
from urllib.parse import urlencode


def build_url(origin, redirect, use_html, reset_cache):
    base = origin.rstrip("/")
    if use_html:
        url = f"{base}/reset_tokens.html"
        if redirect:
            query = urlencode({"redirect": redirect})
            url = f"{url}?{query}"
        return url
    path = redirect or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    url = f"{base}{path}"
    query_data = {"resetTokens": "1"}
    if reset_cache:
        query_data["resetCache"] = "1"
    query = urlencode(query_data)
    return f"{url}?{query}"


def main():
    parser = argparse.ArgumentParser(
        description="Open the UI token reset page (clears localStorage keys starting with 'ui')."
    )
    parser.add_argument(
        "--origin",
        default=os.environ.get("VERA_UI_ORIGIN", "http://127.0.0.1:8788"),
        help="Base URL for the running UI (default: http://127.0.0.1:8788).",
    )
    parser.add_argument(
        "--redirect",
        default="/",
        help="Path to return to after reset (default: /).",
    )
    parser.add_argument(
        "--use-html",
        action="store_true",
        help="Use reset_tokens.html instead of the resetTokens query param.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip clearing service worker caches.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Only print the reset URL (do not open a browser).",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print the reset URL even when opening a browser.",
    )
    args = parser.parse_args()

    url = build_url(args.origin, args.redirect, args.use_html, not args.no_cache)
    if args.print or args.no_open:
        print(url)

    if args.no_open:
        return

    opened = webbrowser.open(url, new=2)
    if not opened:
        print(f"Open this URL in your browser:\n{url}", file=sys.stderr)
        return
    if not args.print:
        print(f"Opened: {url}")


if __name__ == "__main__":
    main()
