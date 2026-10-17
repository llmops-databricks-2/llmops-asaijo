"""Capture only allowlisted Databricks run evidence; never serialize client credentials."""

import argparse
import json
from pathlib import Path

from databricks.sdk import WorkspaceClient

from sdp_framework.workflow import write_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--profile", required=True)
parser.add_argument("--run-id", required=True, type=int)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
workspace = WorkspaceClient(profile=args.profile)
if workspace.config.host.rstrip("/") != "https://dbc-88df4c2c-4033.cloud.databricks.com":
    raise ValueError("Select the course workspace profile")
run = workspace.jobs.get_run(run_id=args.run_id)
gateway_result = None
for task in run.tasks or []:
    if task.task_key == "model_experiments" and task.state and task.state.result_state:
        output = workspace.jobs.get_run_output(run_id=task.run_id)
        if output.notebook_output and output.notebook_output.result:
            try:
                result = json.loads(output.notebook_output.result)
                gateway_result = {key: result[key] for key in ("status", "reason") if key in result}
            except json.JSONDecodeError:
                gateway_result = {"status": "unparsed_notebook_result"}
write_json(
    args.output,
    {
        "run_id": run.run_id,
        "job_id": run.job_id,
        "run_page_url": run.run_page_url,
        "start_time": run.start_time,
        "end_time": run.end_time,
        "result_state": run.state.result_state.value if run.state and run.state.result_state else None,
        "gateway_notebook_result": gateway_result,
        "tasks": [
            {
                "task_key": task.task_key,
                "run_id": task.run_id,
                "result_state": task.state.result_state.value if task.state and task.state.result_state else None,
            }
            for task in run.tasks or []
        ],
    },
)
