# Databricks notebook source
"""Prepare a bounded non-confidential customer dataset in the development schema."""

import json
import sys

from databricks.sdk.runtime import dbutils
from pyspark.sql import SparkSession

from arxiv_curator.config import load_config
from sdp_framework.data import EVENT_SCHEMA, prepare_events, sample_events

dbutils.widgets.text("env", "dev")
env = dbutils.widgets.get("env")
if env != "dev":
    raise ValueError("The course MVP writes only to development")
if sys.version_info[:2] != (3, 12):
    raise RuntimeError("Python 3.12 is required")
cfg = load_config("../../project_config.yml", env=env)
spark = SparkSession.builder.getOrCreate()
rows = prepare_events(sample_events())
prepared = spark.createDataFrame(rows, schema=EVENT_SCHEMA)
table = f"{cfg.full_schema_name}.sdp_prepared_events"
# This dedicated mock table is a complete-feed snapshot, replaced on every run.
prepared.write.format("delta").mode("overwrite").saveAsTable(table)
written = spark.read.table(table)
written.printSchema()
written.select("event_id", "customer_id", "sequence", "invalid_reason").show(10, truncate=False)
assert written.count() == 9
assert written.filter("invalid_reason IS NOT NULL").count() == 2
print(json.dumps({"status": "passed", "table": table, "rows": 9, "quarantined": 2, "python": sys.version.split()[0]}))
