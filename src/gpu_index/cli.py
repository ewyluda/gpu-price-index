"""Command line: ``gpu-index {collect,build,brief,run,show}``."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from gpu_index import brief, publish, store
from gpu_index.pipeline import collect
from gpu_index.sources import ADAPTERS


def cmd_collect(args: argparse.Namespace) -> int:
    run = collect(args.source or None)
    summary = run.to_dict()
    publish.append_run(summary)
    for s in run.sources:
        status = "ok " if s.ok else "ERR"
        print(f"  [{status}] {s.id:8} {s.rows:4} rows  {s.seconds:5.1f}s  {s.error or ''}")
    for level in ("errors", "warnings"):
        for message in summary["validation"][level]:
            print(f"  {level[:-1]}: {message}")
    path = store.path_for(run.stamp.date)
    print(f"{len(run.observations)} observations for {run.stamp.date} -> {path}")
    return 0 if run.ok else 1


def cmd_build(_: argparse.Namespace) -> int:
    snap = publish.build()
    gpus, rows = len(snap["gpus"]), snap["observations"]
    print(f"built site data for {snap['as_of']}: {gpus} GPUs, {rows} rows")
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    snap = json.loads((publish.SITE_DATA / "latest.json").read_text())
    use_llm = True if args.llm else False if args.no_llm else None
    doc = brief.generate(snap, use_llm=use_llm)
    publish.record_llm_usage(doc)
    (publish.SITE_DATA / "brief.json").write_text(json.dumps(doc, indent=1) + "\n")
    if usage := doc.get("usage"):
        cost = "unknown" if usage["usd"] is None else f"${usage['usd']:.4f}"
        print(
            f"Claude usage: {usage['requests']} request(s), {usage['input_tokens']:,} in / "
            f"{usage['output_tokens']:,} out tokens, {cost} "
            f"(month to date: ${usage.get('month_to_date_usd') or 0:.2f})"
        )
    print(f"[{doc['generator']}] {doc['headline']}")
    for bullet in doc["bullets"]:
        print(f"  - {bullet}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    code = cmd_collect(args)
    cmd_build(args)
    cmd_brief(args)
    return code


def cmd_show(_: argparse.Namespace) -> int:
    snap = json.loads((publish.SITE_DATA / "latest.json").read_text())
    print(f"GPU rental index, as of {snap['as_of']} (USD per GPU-hour, on-demand)\n")
    print(f"{'GPU':16}{'Index':>8}{'Hyper':>8}{'Neo':>8}{'Market':>8}{'Premium':>9}{'$/PF-hr':>9}")
    for g in snap["gpus"]:
        s = g["series"]

        def cell(name: str, series: dict[str, dict[str, float]] = s) -> str:
            return f"{series[name]['value']:8.2f}" if name in series else f"{'-':>8}"

        premium = g["hyperscaler_premium"]
        print(
            f"{g['name']:16}{cell('index')}{cell('hyperscaler')}{cell('neocloud')}"
            f"{cell('marketplace')}{(f'{premium:+.0%}' if premium is not None else '-'):>9}"
            f"{g['usd_per_pflop_hour']:9.2f}"
        )
    brief_path = publish.SITE_DATA / "brief.json"
    if brief_path.exists():
        doc = json.loads(brief_path.read_text())
        usage = doc.get("usage")
        line = f"\nBrief: {doc['generator']}"
        if usage:
            cost = "unknown" if usage["usd"] is None else f"${usage['usd']:.4f}"
            mtd = usage.get("month_to_date_usd")
            line += (
                f" ({doc.get('model')}), {usage['requests']} request(s), "
                f"{usage['input_tokens']:,} in / {usage['output_tokens']:,} out tokens, {cost}"
                + (f"; month to date ${mtd:.2f}" if mtd is not None else "")
            )
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="gpu-index", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_source_flag(p: argparse.ArgumentParser) -> None:
        p.add_argument("--source", action="append", choices=sorted(ADAPTERS), help="repeatable")

    def add_llm_flags(p: argparse.ArgumentParser) -> None:
        group = p.add_mutually_exclusive_group()
        group.add_argument("--llm", action="store_true", help="require the Claude-written brief")
        group.add_argument("--no-llm", action="store_true", help="template brief only")

    add_source_flag(sub.add_parser("collect", help="fetch all sources and store today's prices"))
    sub.add_parser("build", help="rebuild site/data from stored observations")
    add_llm_flags(sub.add_parser("brief", help="write the market brief"))
    run = sub.add_parser("run", help="collect + build + brief (what the daily workflow runs)")
    add_source_flag(run)
    add_llm_flags(run)
    sub.add_parser("show", help="print the latest index as a table")

    args = parser.parse_args(argv)
    handlers = {
        "collect": cmd_collect,
        "build": cmd_build,
        "brief": cmd_brief,
        "run": cmd_run,
        "show": cmd_show,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
