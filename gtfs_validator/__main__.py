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

    audit = subparsers.add_parser("audit", help="reconcile CleverCAD and HASTUS, optionally checking the merged GTFS")
    audit.add_argument("clevercad_zip")
    audit.add_argument("hastus_zip")
    audit.add_argument("final_zip", nargs="?", help="optional final merged GTFS ZIP")
    audit.add_argument("--output", help="write the JSON report to this path")
    audit.add_argument('--rail',help='optional separate HASTUS rail ZIP (compared only with final)')

    build = subparsers.add_parser('build-release', help='build a source-only local GTFS merge candidate')
    build.add_argument('--cad',required=True,help='CleverCAD ZIP')
    build.add_argument('--hastus',required=True,help='HASTUS bus ZIP')
    build.add_argument('--rail',help='optional separate HASTUS rail ZIP')
    build.add_argument('--start-date',required=True,help='publication service start YYYYMMDD')
    build.add_argument('--end-date',required=True,help='publication service end YYYYMMDD')
    build.add_argument('--output',required=True,help='new output ZIP; never overwritten')
    build.add_argument('--policy',help='explicit agency merge policy JSON')
    build.add_argument('--sort-reference',help='agency route-sort CSV')
    build.add_argument('--allow-draft',action='store_true',help='permit a reported draft with unresolved joins / validation findings')
    build.add_argument('--reference',help='optional historical final for verification only; never used to generate the candidate')

    compare = subparsers.add_parser('compare-releases',help='independent field/row-level comparison of two GTFS releases')
    compare.add_argument('candidate');compare.add_argument('reference');compare.add_argument('--output',required=True)

    args = parser.parse_args()
    if args.command=='build-release':
        from .release_builder import build_release,DEFAULT_POLICY
        from .release_compare import compare_releases
        from .input_paths import normalize_path
        from pathlib import Path
        try:
            comparison_path=Path(normalize_path(args.output)).with_suffix('.comparison.json')
            if args.reference and comparison_path.exists():raise ValueError('Comparison report already exists; choose a new output name')
            result=build_release(normalize_path(args.cad),normalize_path(args.hastus),normalize_path(args.output),
                                 rail_path=normalize_path(args.rail) if args.rail else None,
                                 start_date=args.start_date,end_date=args.end_date,
                                 policy_path=normalize_path(args.policy) if args.policy else DEFAULT_POLICY,
                                 sort_reference=normalize_path(args.sort_reference) if args.sort_reference else None,
                                 allow_draft=args.allow_draft)
            if args.reference:
                evidence=compare_releases(result['output'],normalize_path(args.reference))
                with comparison_path.open('x',encoding='utf-8') as stream:json.dump(evidence,stream,ensure_ascii=False,indent=2)
                result['reference_equivalent']=evidence['equivalent'];result['comparison_report']=str(comparison_path)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            if args.reference and not result['reference_equivalent']:sys.exit(2)
        except (OSError,ValueError,KeyError) as exc:
            print('Build stopped: '+str(exc),file=sys.stderr);sys.exit(2)
        return
    if args.command=='compare-releases':
        from .release_compare import compare_releases
        from pathlib import Path
        try:
            if Path(args.output).exists():raise ValueError('Comparison output already exists')
            evidence=compare_releases(args.candidate,args.reference)
            with open(args.output,'x',encoding='utf-8') as stream:json.dump(evidence,stream,ensure_ascii=False,indent=2)
            print(json.dumps({'equivalent':evidence['equivalent'],'report':args.output}))
            sys.exit(0 if evidence['equivalent'] else 2)
        except (OSError,ValueError,KeyError) as exc:print(str(exc),file=sys.stderr);sys.exit(2)
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
        report = validate_merge(args.clevercad_zip, args.hastus_zip, args.final_zip, args.rail)
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
