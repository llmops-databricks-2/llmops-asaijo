# Databricks notebook source
"""Opt-in Unity Gateway smoke test; development uses the interactive Codex session."""

import json
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.runtime import dbutils
from pyspark.sql import SparkSession

from arxiv_curator.config import load_config
from sdp_framework.experiment import run_experiments
from sdp_framework.gateway import Gateway

dbutils.widgets.text("env", "dev")
dbutils.widgets.text("use_gateway", "false")
if dbutils.widgets.get("use_gateway").lower() != "true":
    dbutils.notebook.exit(
        json.dumps({"status": "skipped", "reason": "Gateway calls are opt-in; use Codex for development"})
    )
env = dbutils.widgets.get("env")
if env != "dev":
    raise ValueError("Course experiments use development only")
cfg = load_config("../../project_config.yml", env=env)
spec = json.loads(Path("../../examples/customer_history.json").read_text(encoding="utf-8"))
gateway = Gateway(WorkspaceClient(), model=cfg.llm_endpoint)
try:
    records = list(run_experiments(spec, gateway, max_calls=1))
finally:
    gateway.close()
spark = SparkSession.builder.getOrCreate()
payloads = [(record["phase"], json.dumps(record)) for record in records]
spark.createDataFrame(payloads, "phase STRING, experiment_json STRING").write.format("delta").mode(
    "overwrite"
).saveAsTable(f"{cfg.full_schema_name}.sdp_model_experiments")
for record in records:
    print(json.dumps(record))
