#!/usr/bin/env python3
"""Run the example-derived agent evaluation against a live Curio (memo dev/121).

    export CURIO_EVAL_LIVE=1
    python -m utk_curio.tools.agent_eval run \
        --backend-url http://localhost:5002 --token "$CURIO_EVAL_TOKEN" \
        --tier T0,T1 --out .curio/eval

    python -m utk_curio.tools.agent_eval list
    python -m utk_curio.tools.agent_eval export --split validation --out eval.jsonl

What comes out is an **evaluation report**, not a gate: ``report.json`` carries
``isReleaseGate: false`` and ``report.md`` says so in its header. Nothing in
Curio passes or fails because of these numbers, and the first thing to do with a
low score is read the transcript the report kept.

The tool never reads a provider key. Which model answers is whatever the
evaluation account saved in AI Settings; the report records the provider type,
the base URL's host and the model name. Every transcript byte is scrubbed before
it is written.

Cost is not computed unless you supply a rate (``--price-per-mtoken IN,OUT``),
and then it is labelled as yours -- Curio has no price table and will not invent
one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utk_curio.backend.app.agents.evaluation import export as export_mod  # noqa: E402
from utk_curio.backend.app.agents.evaluation import live as live_mod  # noqa: E402
from utk_curio.backend.app.agents.evaluation.canonical import (  # noqa: E402
    TemplateFacts,
)
from utk_curio.backend.app.agents.evaluation.fixtures import (  # noqa: E402
    fixture_paths,
    load_fixture,
)
from utk_curio.backend.app.agents.evaluation.report import (  # noqa: E402
    RunReport,
    new_run_id,
)

DEFAULT_OUT = REPO_ROOT / ".curio" / "eval"


def template_index() -> dict:
    """Manifest facts for every template in this checkout's package catalog.

    Read from ``packages/*/manifest.json`` -- the same source the schema suite
    and the deterministic harness read, so no second table of node kinds
    exists anywhere (``DEC-062``).
    """
    index: dict = {}
    for manifest_path in sorted((REPO_ROOT / "packages").glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        package_id = str(manifest.get("id") or "")
        for template in manifest.get("templates") or []:
            template_id = str(template.get("id") or "")
            if not package_id or not template_id:
                continue
            index[f"{package_id}/{template_id}"] = TemplateFacts(
                template_id=template_id,
                category=str(template.get("category") or "computation"),
                engine=str(template.get("engine") or "python"),
                editor=str(template.get("editor") or "code"),
                has_code=bool(template.get("hasCode")),
                has_grammar=bool(template.get("hasGrammar")),
                behavior=template.get("behavior"),
                backend_handler=template.get("backendHandler"),
            )
    return index


def load_all(fixtures_root: Path | None = None) -> list:
    return [load_fixture(path) for path in fixture_paths(fixtures_root)]


def _examples_for(fixtures) -> dict:
    out: dict = {}
    for fixture in fixtures:
        out[fixture.fixture_id] = json.loads(
            fixture.source_path.read_text(encoding="utf-8")
        )
    return out


def cmd_list(args) -> int:
    fixtures = load_all(args.fixtures)
    print(f"{len(fixtures)} fixtures")
    print(f"{'fixture':44s} {'tier':5s} {'split':11s} review     needs")
    for fixture in fixtures:
        print(
            f"{fixture.fixture_id:44s} {fixture.tier:5s} {fixture.split:11s} "
            f"{fixture.review_status:10s} {','.join(fixture.needs) or '-'}"
        )
    summary = export_mod.split_summary(fixtures)
    print()
    for split, counts in summary.items():
        print(f"{split:11s} total {counts['total']:3d}  approved {counts['approved']:3d}")
    return 0


def cmd_run(args) -> int:
    try:
        live_mod.require_opt_in()
    except live_mod.LiveEvalRefused as refusal:
        # A refusal is an answer, not a crash: an operator who forgot the flag
        # should read one sentence, not a traceback.
        print(f"refused: {refusal}", file=sys.stderr)
        return 3
    if not args.token:
        print(
            "a token for the evaluation account is required (--token, or "
            "CURIO_EVAL_TOKEN); this tool never reads a provider key",
            file=sys.stderr,
        )
        return 2
    fixtures = [
        fixture for fixture in load_all(args.fixtures)
        if not args.only or fixture.fixture_id in set(args.only.split(","))
    ]
    tiers = tuple(t.strip() for t in args.tier.split(",") if t.strip())
    price = None
    if args.price_per_mtoken:
        parts = args.price_per_mtoken.split(",")
        if len(parts) != 2:
            print("--price-per-mtoken takes IN,OUT", file=sys.stderr)
            return 2
        price = (float(parts[0]), float(parts[1]))
    report = RunReport(run_id=new_run_id(), mode="live", price_per_mtoken=price)
    run = live_mod.LiveRun(
        client=live_mod.HttpClient(base_url=args.backend_url, token=args.token),
        templates=template_index(),
        report=report,
        attempts_per_fixture=max(1, args.attempts),
        include_external=args.include_external,
        tiers=tiers,
    )
    try:
        run.run(fixtures, examples=_examples_for(fixtures))
    except live_mod.LiveEvalRefused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 3
    json_path, markdown_path = report.write(Path(args.out))
    print(markdown_path.read_text(encoding="utf-8"))
    print(f"\nwrote {json_path}\nwrote {markdown_path}")
    return 0


def cmd_export(args) -> int:
    fixtures = load_all(args.fixtures)
    try:
        rows = export_mod.rows_for_split(
            fixtures,
            split=args.split,
            purpose=args.purpose,
            require_approved=not args.include_unapproved,
        )
    except export_mod.ExportRefused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 3
    if not rows:
        print(f"nothing to export for split {args.split!r}", file=sys.stderr)
        return 1
    written = export_mod.write_jsonl(rows, Path(args.out))
    print(f"wrote {written} rows to {args.out} (split {args.split}, {args.purpose})")
    print(
        "This file is data. Nothing here trains a model: Curio's provider "
        "abstraction has no fine-tuning contract, and adding one is its own "
        "memo (consent, redaction, cost, cancellation, versioning, evaluation "
        "and rollback)."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent_eval", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--fixtures", type=Path, default=None,
                        help="fixture root (default: docs/examples/prompts)")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="show the fixtures and their splits")
    listing.set_defaults(func=cmd_list)

    run = sub.add_parser("run", help="evaluate against a running Curio (opt-in)")
    run.add_argument("--backend-url", default="http://localhost:5002")
    run.add_argument("--token", default=None,
                     help="bearer token for the evaluation account "
                          "(or CURIO_EVAL_TOKEN)")
    run.add_argument("--tier", default="T0,T1")
    run.add_argument("--only", default="", help="comma-separated fixture ids")
    run.add_argument("--attempts", type=int, default=1)
    run.add_argument("--include-external", action="store_true",
                     help="also run fixtures needing the network or a GPU")
    run.add_argument("--price-per-mtoken", default="",
                     help="IN,OUT rate for an operator-supplied cost estimate")
    run.add_argument("--out", type=Path, default=DEFAULT_OUT)
    run.set_defaults(func=cmd_run)

    exporter = sub.add_parser(
        "export", help="write prompt -> expected pairs for one split"
    )
    exporter.add_argument("--split", required=True,
                          choices=list(export_mod.SPLITS))
    exporter.add_argument("--purpose", default="evaluation",
                          choices=["evaluation", "training"])
    exporter.add_argument("--out", type=Path, required=True)
    exporter.add_argument("--include-unapproved", action="store_true",
                          help="export prompts a person has not reviewed "
                               "(never for training)")
    exporter.set_defaults(func=cmd_export)
    return parser


def main(argv: list | None = None) -> int:
    import os

    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "token", None) is None:
        args.token = os.environ.get("CURIO_EVAL_TOKEN")
    if getattr(args, "purpose", None) == "training" and getattr(
        args, "include_unapproved", False
    ):
        print(
            "refused: unreviewed prompts are never training data (DEC-077)",
            file=sys.stderr,
        )
        return 3
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
