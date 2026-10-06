from __future__ import annotations

import argparse
import json
import sys

from .engine import validate_feed
from .merge import validate_merge
from .web import serve


def main() -> None:
    parser = argparse.ArgumentParser(description="Local OC Transpo GTFS release validator")
    subparsers = parser.add_subparsers(dest="command")

    web = subparsers.add_parser("serve", help="start the localhost web interface")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--open", action="store_true", help="open the interface in the default browser")

    validate = subparsers.add_parser("validate", help="validate one GTFS ZIP")
    validate.add_argument("zip_path")
    validate.add_argument("--output", help="write the JSON report to this path")

    audit = subparsers.add_parser("audit", help="reconcile CleverCAD, HASTUS, and the merged GTFS")
    audit.add_argument("clevercad_zip")
    audit.add_argument("hastus_zip")
    audit.add_argument("final_zip")
    audit.add_argument("--output", help="write the JSON report to this path")

    args = parser.parse_args()
    if args.command in {None, "serve"}:
        serve(
            getattr(args, "host", "127.0.0.1"),
            getattr(args, "port", 8765),
            getattr(args, "open", False),
        )
        return
    if args.command == "validate":
        report = validate_feed(args.zip_path)
        rendered = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as stream:
                stream.write(rendered)
                stream.write("\n")
        else:
            print(rendered)
        sys.exit(2 if report.decision == "BLOCKED" else 1 if report.decision == "NEEDS REVIEW" else 0)
    if args.command == "audit":
        report = validate_merge(args.clevercad_zip, args.hastus_zip, args.final_zip)
        rendered = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as stream:
                stream.write(rendered)
                stream.write("\n")
        else:
            print(rendered)
        sys.exit(2 if report.decision == "BLOCKED" else 1 if report.decision == "NEEDS REVIEW" else 0)


if __name__ == "__main__":
    main()
