"""Small course-relevant prompt experiments, separate from deployment and design approval."""

import json
from collections.abc import Iterator

from sdp_framework.gateway import Gateway
from sdp_framework.workflow import validate_spec


def run_experiments(spec: dict, gateway: Gateway, max_calls: int = 1) -> Iterator[dict]:
    """Run one small smoke test by default; extra course prompts require an explicit limit."""
    validate_spec(spec)
    if not 1 <= max_calls <= 3:
        raise ValueError("max_calls must be between 1 and 3")
    prompts = (
        ("architecture", "Propose Bronze/Silver/Gold architecture and identify missing requirements."),
        ("duplicate_history", "Explain expected history for unchanged UPSERTs, duplicates, DELETE and reinsertion."),
        ("test_review", "Generate boundary tests and integration scenarios; list unsupported assumptions."),
    )
    for phase, question in prompts[:max_calls]:
        yield gateway.ask(question + "\nSpecification:\n" + json.dumps(spec), phase)
