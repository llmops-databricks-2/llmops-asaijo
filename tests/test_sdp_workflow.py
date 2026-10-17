"""Review boundary, generator and model experiment contract tests."""

import ast
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from sdp_framework.gateway import Gateway, WorkspaceAuth, response_text
from sdp_framework.workflow import approve, generate, propose, validate_spec

ROOT = Path(__file__).resolve().parents[1]


def spec() -> dict:
    """Read the course use case."""
    return json.loads((ROOT / "examples/customer_history.json").read_text())


def test_requires_explicit_approval(tmp_path: Path) -> None:
    """Generating before review must fail without producing executable artifacts."""
    propose(spec(), tmp_path)
    with pytest.raises(FileNotFoundError):
        generate(tmp_path)
    with pytest.raises(ValueError, match="reviewer"):
        approve(tmp_path, "Atsushi", False)
    assert not (tmp_path / "generated").exists()


def test_tampered_design_invalidates_approval(tmp_path: Path) -> None:
    """Even a changed model-review comment requires review again."""
    design = propose(spec(), tmp_path)
    approve(tmp_path, "test reviewer", True)
    design["dependencies"] = "changed"
    (tmp_path / "architecture.json").write_text(json.dumps(design))
    with pytest.raises(ValueError, match="changed"):
        generate(tmp_path)


@pytest.mark.parametrize("field", ["rules", "source_schema", "target_columns", "pattern"])
def test_unsupported_requirements_fail(field: str) -> None:
    """Never silently substitute unsupported project semantics."""
    changed = spec()
    changed[field] = "unsupported"
    with pytest.raises(ValueError):
        validate_spec(changed)


def test_generated_tests_execute(tmp_path: Path) -> None:
    """Render, parse and actually run generated tests using independent fixtures."""
    propose(spec(), tmp_path)
    approve(tmp_path, "automated-test-fixture-only", True)
    generate(tmp_path)
    generated = tmp_path / "generated"
    ast.parse((generated / "customer_pipeline.py").read_text())
    manifest = json.loads((generated / "manifest.json").read_text())
    assert manifest["test_status"] == "generated_not_executed"
    assert (generated / "customer_pipeline.py").read_text() == (
        ROOT / "src/pipelines/customers/transformations/customer_pipeline.py"
    ).read_text()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(generated / "test_customer.py"), "-q"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "10 passed" in result.stdout
    with pytest.raises(ValueError, match="already exists"):
        generate(tmp_path)


def test_gateway_auth_refreshes() -> None:
    """Use renewable WorkspaceClient auth and ensure the dummy SDK key is overwritten."""
    values = iter(["Bearer first-test-value", "Bearer refreshed-test-value"])
    workspace = SimpleNamespace(config=SimpleNamespace(authenticate=lambda: {"Authorization": next(values)}))
    auth = WorkspaceAuth(workspace)
    for expected in ("Bearer first-test-value", "Bearer refreshed-test-value"):
        request = httpx.Request("POST", "https://example.test", headers={"Authorization": "Bearer dummy"})
        assert next(auth.auth_flow(request)).headers["Authorization"] == expected


def test_gateway_allowlisted_evidence() -> None:
    """Record text, tokens and truncation while excluding raw response metadata."""
    gateway = object.__new__(Gateway)
    gateway.model = "course_ops.gateway.chat"
    gateway.max_tokens = 256
    calls = []

    def complete(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="Review this assumption"), finish_reason="length")
            ],
            usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}),
            hidden_header="must not persist",
        )

    gateway.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    evidence = gateway.ask("mock prompt", "architecture")
    assert evidence["usage"]["total_tokens"] == 20
    assert "Output reached token limit." in evidence["limitations"]
    assert "hidden_header" not in evidence
    assert calls[0]["max_tokens"] == 256


def test_live_stages_are_review_artifacts(tmp_path: Path) -> None:
    """Call all LLM stages while executable code remains the supported pattern."""
    calls = []

    def ask(prompt: str, phase: str) -> dict:
        calls.append(phase)
        return {"phase": phase, "response": "example suggestion", "usage": {"total_tokens": 1}}

    gateway = SimpleNamespace(ask=ask)
    propose(spec(), tmp_path, gateway)
    approve(tmp_path, "test-fixture-reviewer", True)
    generate(tmp_path, gateway)
    assert calls == ["architecture", "implementation", "unit_testing", "integration_review"]


def test_gateway_content_blocks() -> None:
    """Handle the structured content blocks observed in the live course gateway response."""
    assert response_text([{"type": "reasoning", "summary": []}, {"type": "text", "text": "review"}]) == "review"
    assert response_text(None) == ""


def test_codex_reviews_need_no_gateway(tmp_path: Path) -> None:
    """Use interactive-session notes for every stage with zero live model calls."""
    reviews = json.loads((ROOT / "examples/codex_session_review.json").read_text())
    design = propose(spec(), tmp_path, reviews=reviews)
    assert design["mode"] == "codex_session"
    assert design["model_review"] is None
    approve(tmp_path, "automated-test-fixture-only", True)
    generate(tmp_path, reviews=reviews)
    manifest = json.loads((tmp_path / "generated/manifest.json").read_text())
    assert manifest["gateway_calls"] == 0
    assert manifest["review_backend"] == "codex_session"


def test_cli_defaults_to_zero_gateway_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Even a supplied profile must not implicitly enable inference during development."""
    from sdp_framework import cli

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Default development commands must not instantiate remote clients")

    monkeypatch.setattr(cli, "WorkspaceClient", forbidden)
    monkeypatch.setattr(cli, "Gateway", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sdp-framework",
            "propose",
            "--spec",
            str(ROOT / "examples/customer_history.json"),
            "--work-dir",
            str(tmp_path),
            "--profile",
            "unused-profile",
            "--review-file",
            str(ROOT / "examples/codex_session_review.json"),
        ],
    )
    cli.main()
    design = json.loads((tmp_path / "architecture.json").read_text())
    assert design["mode"] == "codex_session"


def test_gateway_smoke_default_is_one_call() -> None:
    """A smoke test does not silently expand into multiple model experiments."""
    from sdp_framework.experiment import run_experiments

    calls = []

    def ask(prompt: str, phase: str) -> dict:
        calls.append(phase)
        return {"phase": phase}

    assert len(list(run_experiments(spec(), SimpleNamespace(ask=ask)))) == 1
    assert calls == ["architecture"]
