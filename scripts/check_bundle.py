"""Validate bundle files offline against the installed Databricks CLI JSON schema."""

import json
import subprocess
from pathlib import Path

import jsonschema
import regex
import yaml

root = Path(__file__).resolve().parents[1]
schema = json.loads(subprocess.check_output(["databricks", "bundle", "schema"], text=True, encoding="utf-8"))


def merge(left: dict, right: dict) -> dict:
    """Merge included YAML objects in the same shape used by the bundle."""
    for key, value in right.items():
        if key in left and isinstance(left[key], dict) and isinstance(value, dict):
            merge(left[key], value)
        else:
            left[key] = value
    return left


bundle = yaml.safe_load((root / "databricks.yml").read_text(encoding="utf-8"))
for pattern in bundle["include"]:
    for path in sorted(root.glob(pattern)):
        merge(bundle, yaml.safe_load(path.read_text(encoding="utf-8")))


def unicode_pattern(validator, pattern: str, instance: object, subschema):  # noqa: ANN001, ANN201
    """Honor the CLI schema's Unicode property classes, unsupported by Python re."""
    if isinstance(instance, str) and not regex.search(pattern, instance):
        yield jsonschema.ValidationError(f"{instance!r} does not match {pattern!r}")


validator = jsonschema.validators.extend(jsonschema.Draft202012Validator, {"pattern": unicode_pattern})
validator(schema).validate(bundle)
for target in ("acc", "prd"):
    assert not bundle["targets"][target].get("resources"), "SDP resources must be dev-only"
resources = bundle["targets"]["dev"]["resources"]
job = resources["jobs"]["sdp_course_workflow"]
assert job["environments"][0]["spec"]["environment_version"] == "5"
assert job["budget_policy_id"] == "${var.usage_policy_id}"
assert job["performance_target"] == "STANDARD"
assert job["parameters"] == [{"name": "use_gateway", "default": "false"}]
pipeline = resources["pipelines"]["sdp_customer_history"]
assert pipeline["serverless"] is True
assert pipeline["budget_policy_id"] == "${var.usage_policy_id}"
print(
    json.dumps(
        {
            "status": "passed",
            "validation": "offline_cli_json_schema",
            "workspace_validation": "not_executed",
            "sdp_target": "dev",
            "notebook_environment": "5",
        }
    )
)
