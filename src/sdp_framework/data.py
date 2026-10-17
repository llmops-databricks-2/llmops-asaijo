"""Validate bounded mock events and provide an independent history oracle."""

import json
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

EVENT_SCHEMA = (
    "event_id STRING, customer_id STRING, sequence BIGINT, event_time STRING, "
    "operation STRING, name STRING, email STRING, invalid_reason STRING, raw_json STRING"
)
HISTORY_COLUMNS = ["customer_id", "name", "email", "valid_from", "valid_to"]


def asset_json(name: str) -> Any:  # noqa: ANN401
    """Load a versioned, non-confidential project fixture."""
    return json.loads(files("sdp_framework").joinpath("assets", name).read_text(encoding="utf-8"))


def sample_events() -> list[dict]:
    """Load the deliberately unordered mock customer change feed."""
    text = files("sdp_framework").joinpath("assets", "customer_events.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def normalize_event(raw: dict) -> dict:
    """Normalize full-image UPSERTs and DELETEs; retain rejected inputs for quarantine."""
    result = dict.fromkeys(["event_id", "customer_id", "sequence", "event_time", "operation", "name", "email"])
    result["raw_json"] = json.dumps(raw, sort_keys=True)
    errors = []
    for key in ("event_id", "customer_id", "operation", "name", "email"):
        value = raw.get(key)
        result[key] = value.strip() if isinstance(value, str) else None
    result["operation"] = (result["operation"] or "").upper()
    result["email"] = (result["email"] or "").lower() or None
    if not result["event_id"] or not result["customer_id"]:
        errors.append("missing_key")
    seq = raw.get("sequence")
    if type(seq) is not int or not 0 < seq < 2**63:
        errors.append("invalid_sequence")
    else:
        result["sequence"] = seq
    try:
        timestamp = datetime.fromisoformat(str(raw.get("event_time", "")).replace("Z", "+00:00"))
        if timestamp.utcoffset() is None:
            raise ValueError("timezone required")
        result["event_time"] = timestamp.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        errors.append("invalid_timestamp")
    if result["operation"] not in {"UPSERT", "DELETE"}:
        errors.append("invalid_operation")
    if result["operation"] == "UPSERT":
        email = result["email"] or ""
        if not result["name"] or email.count("@") != 1 or not all(email.split("@")):
            errors.append("invalid_full_image")
    else:
        result["name"] = result["email"] = None
    result["invalid_reason"] = ",".join(errors) or None
    return result


def prepare_events(raw_events: list[dict]) -> list[dict]:
    """Keep exact duplicates; fail on ambiguous identity, ordering or sequence conflicts."""
    prepared = [normalize_event(raw) for raw in raw_events]
    identities = {}
    sequences = {}
    for event in prepared:
        if event["invalid_reason"]:
            continue
        payload = {key: value for key, value in event.items() if key != "raw_json"}
        event_id = event["event_id"]
        if event_id in identities and identities[event_id] != payload:
            raise ValueError(f"Conflicting event_id: {event_id}")
        identities[event_id] = payload
        key = (event["customer_id"], event["sequence"])
        if key in sequences and sequences[key] != payload:
            raise ValueError(f"Conflicting customer sequence: {key}")
        sequences[key] = payload
    previous = {}
    for key, event in sorted(sequences.items()):
        customer = key[0]
        if customer in previous and event["event_time"] <= previous[customer]:
            raise ValueError(f"Non-increasing timestamp for {customer}")
        previous[customer] = event["event_time"]
    return prepared


def reference_history(prepared: list[dict]) -> list[dict]:
    """Calculate expected SCD2 intervals without Spark; DELETE closes the active row."""
    events = {event["event_id"]: event for event in prepared if not event["invalid_reason"]}
    history = []
    active = {}
    for event in sorted(events.values(), key=lambda e: (e["customer_id"], e["sequence"])):
        customer = event["customer_id"]
        current = active.get(customer)
        if (
            current
            and event["operation"] == "UPSERT"
            and all(current[field] == event[field] for field in ("name", "email"))
        ):
            continue
        if current:
            current["valid_to"] = event["event_time"]
            active.pop(customer)
        if event["operation"] == "UPSERT":
            row = {field: event[field] for field in ("customer_id", "name", "email")}
            row.update(valid_from=event["event_time"], valid_to=None)
            history.append(row)
            active[customer] = row
    return history
