"""Command-line entry point for the review-gated generation workflow."""

import argparse
import json
from pathlib import Path

from databricks.sdk import WorkspaceClient

from sdp_framework.gateway import Gateway
from sdp_framework.workflow import approve, generate, propose, write_json


def main() -> None:
    """Run a stage; never execute generated model code or automatically approve a design."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("propose", "generate", "experiment"):
        command = commands.add_parser(name)
        command.add_argument("--work-dir", type=Path, required=True)
        command.add_argument("--profile", help="Explicit course workspace profile for local inference")
        command.add_argument("--backend", choices=("codex", "gateway", "template"), default="codex")
        command.add_argument("--review-file", type=Path, help="Review notes authored in the interactive Codex session")
        command.add_argument("--offline", action="store_true", help="Alias for --backend template")
        command.add_argument("--max-tokens", type=int, default=256, help="Gateway output cap per call (1-1024)")
        if name == "experiment":
            command.add_argument("--max-calls", type=int, choices=(1, 2, 3), default=1)
        if name in {"propose", "experiment"}:
            command.add_argument("--spec", type=Path, required=True)
    approval = commands.add_parser("approve")
    approval.add_argument("--work-dir", type=Path, required=True)
    approval.add_argument("--reviewer", required=True)
    approval.add_argument("--accept-assumptions", action="store_true")
    args = parser.parse_args()
    if args.command == "approve":
        approve(args.work_dir, args.reviewer, args.accept_assumptions)
        return
    backend = "template" if args.offline else args.backend
    if backend == "gateway" and not args.profile:
        parser.error("Gateway calls require an explicit --profile")
    if args.command == "experiment" and backend != "gateway":
        parser.error("Model experiments require explicit --backend gateway and --profile")
    reviews = json.loads(args.review_file.read_text(encoding="utf-8")) if args.review_file else None
    if reviews and backend != "codex":
        parser.error("--review-file is for --backend codex")
    gateway = (
        Gateway(WorkspaceClient(profile=args.profile), max_tokens=args.max_tokens) if backend == "gateway" else None
    )
    try:
        if args.command == "propose":
            propose(json.loads(args.spec.read_text(encoding="utf-8")), args.work_dir, gateway, reviews=reviews)
        elif args.command == "generate":
            generate(args.work_dir, gateway, reviews=reviews)
        else:
            from sdp_framework.experiment import run_experiments

            for result in run_experiments(
                json.loads(args.spec.read_text(encoding="utf-8")), gateway, max_calls=args.max_calls
            ):
                write_json(args.work_dir / f"{result['phase']}.json", result)
    finally:
        if gateway:
            gateway.close()
