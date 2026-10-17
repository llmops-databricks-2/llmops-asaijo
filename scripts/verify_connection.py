"""Prove local Python 3.12 can execute Spark remotely with a selected Databricks profile."""

import argparse
import json
import sys

from databricks.connect import DatabricksSession
from databricks.sdk import WorkspaceClient

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--profile", required=True)
args = parser.parse_args()
if sys.version_info[:2] != (3, 12):
    raise RuntimeError("Use the project's Python 3.12 environment")
workspace = WorkspaceClient(profile=args.profile)
if workspace.config.host.rstrip("/") != "https://dbc-88df4c2c-4033.cloud.databricks.com":
    raise ValueError("Selected profile does not point to the configured course workspace")
spark = DatabricksSession.builder.profile(args.profile).serverless(True).getOrCreate()
assert spark.range(3).count() == 3
print(
    json.dumps({"status": "passed", "host": workspace.config.host, "python": sys.version.split()[0], "remote_rows": 3})
)
