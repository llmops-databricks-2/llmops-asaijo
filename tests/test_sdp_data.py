"""Independent acceptance cases for mock preparation and the history oracle."""

import copy

import pytest

from sdp_framework.data import asset_json, normalize_event, prepare_events, reference_history, sample_events


def test_complete_history() -> None:
    """Check exact independent interval boundaries, including delete gaps."""
    prepared = prepare_events(sample_events())
    assert sum(row["invalid_reason"] is not None for row in prepared) == 2
    assert reference_history(prepared) == asset_json("expected_history.json")
    assert reference_history(prepare_events(sample_events()[::-1])) == asset_json("expected_history.json")
    assert reference_history(prepare_events(sample_events() * 2)) == asset_json("expected_history.json")


@pytest.mark.parametrize(
    "patch,reason",
    [
        ({"customer_id": " "}, "missing_key"),
        ({"event_time": "2026-01-01"}, "invalid_timestamp"),
        ({"event_time": "2026-01-01T00:00:00"}, "invalid_timestamp"),
        ({"sequence": True}, "invalid_sequence"),
        ({"sequence": 0}, "invalid_sequence"),
        ({"sequence": 2**63}, "invalid_sequence"),
        ({"operation": "TRUNCATE"}, "invalid_operation"),
        ({"email": "missing-at"}, "invalid_full_image"),
        ({"name": None}, "invalid_full_image"),
    ],
)
def test_invalid_inputs(patch: dict, reason: str) -> None:
    """Quarantine boundary and malformed cases with useful reasons."""
    raw = sample_events()[1] | patch
    assert reason in normalize_event(raw)["invalid_reason"]


def test_normalization_and_timezone() -> None:
    """Normalize whitespace, operation case, email case and timezone offsets."""
    result = normalize_event(sample_events()[1] | {"event_time": "2026-01-01T01:00:00+01:00"})
    assert result["invalid_reason"] is None
    assert (result["customer_id"], result["name"], result["email"]) == ("C001", "Alice", "alice@example.test")
    assert result["event_time"] == "2026-01-01T00:00:00.000000Z"


@pytest.mark.parametrize(
    "patch",
    [
        {"email": "conflict@example.test"},
        {"event_id": "different-id"},
    ],
)
def test_ambiguous_events_fail(patch: dict) -> None:
    """Never pick an arbitrary record when IDs or customer sequences conflict."""
    original = sample_events()[1]
    with pytest.raises(ValueError, match="Conflicting"):
        prepare_events([original, original | patch])


def test_timestamp_order_must_match_sequence() -> None:
    """Reject zero-length or backwards history intervals before writing Delta."""
    original = sample_events()[1]
    with pytest.raises(ValueError, match="Non-increasing"):
        prepare_events([original, original | {"event_id": "next", "sequence": 2}])


def test_absent_and_repeated_delete() -> None:
    """Deleting an absent customer has no history; repeated deletes preserve the first closure."""
    original = sample_events()[1]
    delete = original | {"operation": "DELETE"}
    assert reference_history(prepare_events([delete])) == []
    rows = [
        original,
        delete | {"event_id": "d1", "sequence": 2, "event_time": "2026-01-02T00:00:00Z"},
        delete | {"event_id": "d2", "sequence": 3, "event_time": "2026-01-03T00:00:00Z"},
    ]
    history = reference_history(prepare_events(rows))
    assert len(history) == 1
    assert history[0]["valid_to"] == "2026-01-02T00:00:00.000000Z"


def test_input_is_not_mutated() -> None:
    """Preparation retains the input records as supplied."""
    raw = sample_events()
    before = copy.deepcopy(raw)
    prepare_events(raw)
    assert raw == before
