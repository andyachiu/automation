#!/usr/bin/env python3
"""Inspect and manage local briefing memory without API calls or message delivery."""
import argparse
import json
import sys
from shared.memory import MemoryError, configured_store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Show counts and retention, without private content")
    commands.add_parser("show", help="Print stored briefing text and preferences locally")
    preference = commands.add_parser("set-preference", help="Save an explicit presentation preference")
    preference.add_argument("key")
    preference.add_argument("value")
    forget = commands.add_parser("forget-preference")
    forget.add_argument("key")
    clear = commands.add_parser("clear", help="Remove all history and saved preferences")
    clear.add_argument("--yes", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        store = configured_store()
        if store is None:
            print("Memory is disabled by AUTOMATION_MEMORY_ENABLED=0.")
            return 0 if args.command == "status" else 1
        if args.command in {"status", "show"}:
            print(json.dumps(store.snapshot(include_content=args.command == "show"), indent=2, ensure_ascii=False))
        elif args.command == "set-preference":
            store.set_preference(args.key, args.value)
            print("Preference saved.")
        elif args.command == "forget-preference":
            store.forget_preference(args.key)
            print("Preference removed.")
        elif args.command == "clear":
            store.clear()
            print("Briefing history and preferences cleared.")
        return 0
    except (MemoryError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
