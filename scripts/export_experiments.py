"""Export allowlisted model experiment records from the course development table."""

import argparse
import json
from pathlib import Path

from databricks.connect import DatabricksSession
from databricks.sdk import WorkspaceClient

from sdp_framework.workflow import write_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--profile", required=True)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
workspace = WorkspaceClient(profile=args.profile)
if workspace.config.host.rstrip("/") != "https://dbc-88df4c2c-4033.cloud.databricks.com":
    raise ValueError("Select the course workspace profile")
spark = DatabricksSession.builder.profile(args.profile).serverless(True).getOrCreate()
allowed = {"phase", "timestamp_utc", "model", "prompt", "response", "usage", "finish_reason", "limitations"}
records = []
for row in spark.table("llmops_dev.asaijo.sdp_model_experiments").select("experiment_json").limit(10).collect():
    record = json.loads(row.experiment_json)
    records.append({key: value for key, value in record.items() if key in allowed})
write_json(args.output, sorted(records, key=lambda record: record["phase"]))
