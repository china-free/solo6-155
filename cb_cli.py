import argparse
import sys

import cb_store
import cb_watcher
import cb_search


def cmd_daemon(args):
    cb_store.init_db()
    w = cb_watcher.ClipboardWatcher()
    w.run()


def cmd_search(args):
    cb_search.interactive_search(
        query=args.query,
        use_regex=args.regex,
        today_only=not args.all,
    )


def cmd_list(args):
    cb_store.init_db()
    rows = cb_store.list_recent(limit=args.n)
    if not rows:
        print("(empty)")
        return
    for row in rows:
        ts = cb_search._ts_to_str(row["created_at"])
        preview = cb_search._truncate(row["content"], 120)
        print(f"[{ts}] #{row['id']:>5}  {preview}")


def cmd_clear(args):
    cb_store.init_db()
    if not args.yes:
        answer = input("Clear ALL clipboard history? [y/N] ").strip().lower()
        if answer != "y":
            print("aborted.")
            return
    cb_store.clear_all()
    print("history cleared.")


def build_parser():
    p = argparse.ArgumentParser(
        prog="cb",
        description="Minimal terminal clipboard manager. Start daemon in background first.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("daemon", help="Run clipboard watcher (blocking, background it yourself).")

    sp = sub.add_parser("search", help="Interactively search history and pick one to re-copy.")
    sp.add_argument("query", nargs="?", default=None, help="Search text (default: all entries).")
    sp.add_argument("--regex", "-r", action="store_true", help="Treat query as regex.")
    sp.add_argument("--all", "-a", action="store_true", help="Search across all days (default: today only).")

    lp = sub.add_parser("list", help="List the most recent entries non-interactively.")
    lp.add_argument("-n", type=int, default=30, help="Number of entries to show (default 30).")

    cp = sub.add_parser("clear", help="Clear all history.")
    cp.add_argument("-y", "--yes", action="store_true", help="Skip confirmation.")

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "daemon":
        cmd_daemon(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "clear":
        cmd_clear(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
