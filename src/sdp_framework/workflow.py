"""Stage generation, bind review to content hashes, and render a fixed supported pattern."""

import hashlib
import json
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from sdp_framework.gateway import Gateway

RULES = {
    "images": "full",
    "order": "sequence_per_customer",
    "timestamps": "strictly_increasing_per_customer",
    "duplicates": "deduplicate_event_id_fail_conflicts",
    "invalid_data": "quarantine",
    "unchanged_images": "suppress",
    "deletes": "close_history",
    "reinsert": "new_version",
    "reprocessing": "recompute_complete_feed",
    "intervals": "half_open_utc",
}
SOURCE_SCHEMA = {
    "event_id": "string",
    "customer_id": "string",
    "sequence": "long",
    "event_time": "ISO8601 with timezone",
    "operation": "UPSERT or DELETE",
    "name": "string",
    "email": "string",
}
TARGET_COLUMNS = ["customer_id", "name", "email", "valid_from", "valid_to"]


def write_json(path: Path, value: object) -> None:
    """Write a reviewable UTF-8 artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def digest(value: object) -> str:
    """Hash canonical content so any changed design requires review again."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_spec(spec: dict) -> None:
    """Reject missing or unsupported requirements rather than silently changing semantics."""
    allowed = {"use_case", "users", "pattern", "source_schema", "target_columns", "rules", "assumptions"}
    if set(spec) != allowed or not isinstance(spec["use_case"], str) or not spec["use_case"].strip():
        raise ValueError("Provide exactly use_case, users, pattern, source_schema, target_columns, rules, assumptions")
    if not spec["users"] or not spec["assumptions"]:
        raise ValueError("Users and assumptions must be explicit")
    if spec["pattern"] != "customer_history_batch_v1" or spec["rules"] != RULES:
        raise ValueError("Unsupported or missing rule: this MVP supports only customer_history_batch_v1")
    if spec["source_schema"] != SOURCE_SCHEMA or spec["target_columns"] != TARGET_COLUMNS:
        raise ValueError("Source/target schema does not match the supported customer-history pattern")


def propose(spec: dict, output: Path, gateway: Gateway | None = None, reviews: dict | None = None) -> dict:
    """Create an unapproved proposal; offline mode makes no model-call claims."""
    validate_spec(spec)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Proposal output must be empty; use a new directory to preserve earlier evidence")
    design = {
        "spec": spec,
        "tables": {
            "sdp_bronze_customers": "Materialized view of the complete prepared feed, including rejected rows",
            "sdp_customer_quarantine": "Materialized view of invalid rows and reasons",
            "sdp_silver_customers": "Materialized view of valid normalized, deduplicated events",
            "sdp_gold_customer_history": "Materialized view of half-open UTC history intervals",
        },
        "dependencies": "prepared Delta -> Bronze -> Silver -> Gold; Bronze -> quarantine",
        "execution": "Triggered serverless batch; complete-feed history recomputation",
        "model_review": gateway.ask(
            "Review this fixed design. Identify missing requirements, risks and acceptance tests:\n" + json.dumps(spec),
            "architecture",
        )
        if gateway
        else None,
        "codex_review": reviews.get("architecture") if reviews else None,
        "mode": "unity_gateway" if gateway else "codex_session" if reviews else "offline_template",
    }
    write_json(output / "architecture.json", design)
    (output / "REVIEW.md").write_text(
        "# Architecture review\n\nReview architecture.json, including model suggestions and assumptions. "
        "Resolve concerns by revising the specification and proposing again in a new directory. "
        "Only the fixed contract is executable; model comments do not change the contract.\n\n"
        "Approve explicitly with `sdp-framework approve --work-dir <dir> --reviewer <name> "
        "--accept-assumptions`. Any content change invalidates approval.\n",
        encoding="utf-8",
    )
    return design


def approve(output: Path, reviewer: str, accept_assumptions: bool) -> None:
    """Record an explicit human review assertion bound to the entire architecture."""
    if not accept_assumptions or not reviewer.strip():
        raise ValueError("A reviewer and explicit acceptance of assumptions are required")
    design = json.loads((output / "architecture.json").read_text(encoding="utf-8"))
    validate_spec(design["spec"])
    write_json(
        output / "approval.json",
        {
            "architecture_sha256": digest(design),
            "reviewer": reviewer,
            "accepted_assumptions": True,
            "timestamp_utc": datetime.now(UTC).isoformat(),
        },
    )


def generate(output: Path, gateway: Gateway | None = None, reviews: dict | None = None) -> None:
    """Render trusted starter code and tests after review; keep LLM suggestions as text."""
    design = json.loads((output / "architecture.json").read_text(encoding="utf-8"))
    approval = json.loads((output / "approval.json").read_text(encoding="utf-8"))
    if approval.get("architecture_sha256") != digest(design) or approval.get("accepted_assumptions") is not True:
        raise ValueError("Architecture changed or was not approved; review and approve it again")
    validate_spec(design["spec"])
    generated = output / "generated"
    if generated.exists():
        raise ValueError("Generation already exists; use a new proposal directory")
    generated.mkdir(parents=True)
    for template, filename in (("pipeline.py.txt", "customer_pipeline.py"), ("unit_tests.py.txt", "test_customer.py")):
        text = files("sdp_framework").joinpath("templates", template).read_text(encoding="utf-8")
        (generated / filename).write_text(text, encoding="utf-8")
    # Expected results are hand-authored fixtures, independent of the implementation/oracle.
    for filename in ("expected_history.json", "customer_events.jsonl"):
        (generated / filename).write_text(
            files("sdp_framework").joinpath("assets", filename).read_text(encoding="utf-8"), encoding="utf-8"
        )
    write_json(generated / "integration_scenarios.json", integration_scenarios())
    if reviews:
        write_json(generated / "codex_session_reviews.json", reviews)
    if gateway:
        for phase, instruction in (
            ("implementation", "Suggest modern Python SDP implementation and review the fixed batch design."),
            ("unit_testing", "Suggest independent unit tests, boundary inputs and exact expected outputs."),
            ("integration_review", "Review requirements coverage; propose integration tests and unresolved risks."),
        ):
            write_json(
                generated / f"{phase}_suggestions.json",
                gateway.ask(instruction + "\nApproved architecture:\n" + json.dumps(design), phase),
            )
    write_json(
        generated / "manifest.json",
        {
            "architecture_sha256": digest(design),
            "approval": approval,
            "code_origin": "versioned fixed-pattern template; model suggestions are review artifacts",
            "review_backend": "unity_gateway" if gateway else "codex_session" if reviews else "template",
            "gateway_calls": 3 if gateway else 0,
            "test_status": "generated_not_executed",
            "integration_status": "scenarios_not_executed",
            "files_sha256": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(generated.iterdir())
            },
        },
    )


def integration_scenarios() -> list[dict]:
    """Declare expected outcomes without misrepresenting them as executed tests."""
    return [
        {"scenario": name, "expected": expected, "status": "not_executed"}
        for name, expected in (
            ("initial_load", "C001 and C002 each have one current version"),
            ("update", "C001 first version ends Jan 3; second starts Jan 3"),
            ("unchanged_image", "Jan 2 unchanged UPSERT creates no version"),
            ("delete", "C001 second version closes Jan 4; no active version until Jan 5"),
            ("reinsertion", "C001 new version starts Jan 5 even with same attributes"),
            ("duplicates", "duplicate e1 creates no unintended version"),
            ("out_of_order", "e3 arriving before e1 produces the same ordered history"),
            ("invalid_data", "two fixture rows quarantined; seven accepted rows before dedup, six after"),
            ("reprocessing", "same complete feed yields exactly the same four history rows"),
            ("conflict", "conflicting IDs/sequences or timestamp ordering fail preparation"),
        )
    ]
