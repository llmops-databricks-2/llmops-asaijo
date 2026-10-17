# Databricks notebook source
"""Verify the actual Spark transformations and deployed tables against independent fixtures."""

import json
from datetime import UTC

from databricks.sdk.runtime import dbutils
from pyspark.sql import SparkSession

from arxiv_curator.config import load_config
from sdp_framework.data import EVENT_SCHEMA, HISTORY_COLUMNS, asset_json, prepare_events, sample_events
from sdp_framework.transforms import clean_events, customer_history

dbutils.widgets.text("env", "dev")
env = dbutils.widgets.get("env")
if env != "dev":
    raise ValueError("The course MVP verifies only development")
cfg = load_config("../../project_config.yml", env=env)
spark = SparkSession.builder.getOrCreate()
expected = asset_json("expected_history.json")


def collect_history(frame) -> list[dict]:  # noqa: ANN001
    """Normalize collected UTC intervals into the fixture representation."""
    rows = []
    for record in frame.select(*HISTORY_COLUMNS).orderBy("customer_id", "valid_from").collect():
        row = record.asDict()
        for column in ("valid_from", "valid_to"):
            value = row[column]
            if value is not None:
                # Connect may return naive UTC timestamps; timestamps with a timezone are converted.
                value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
                row[column] = value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        rows.append(row)
    return rows


# Spark unit/integration checks use production functions, not just the Python oracle.
raw = sample_events()
for scenario, events in (("complete_feed", raw), ("duplicate_replay", raw + raw), ("reversed_arrival", raw[::-1])):
    actual = customer_history(clean_events(spark.createDataFrame(prepare_events(events), EVENT_SCHEMA)))
    assert collect_history(actual) == expected, scenario

prefix = cfg.full_schema_name
assert spark.table(f"{prefix}.sdp_bronze_customers").count() == 9
assert spark.table(f"{prefix}.sdp_customer_quarantine").count() == 2
assert spark.table(f"{prefix}.sdp_silver_customers").count() == 6
assert collect_history(spark.table(f"{prefix}.sdp_gold_customer_history")) == expected
print(
    json.dumps(
        {
            "status": "passed",
            "history_rows": 4,
            "quarantined": 2,
            "checks": ["complete_feed", "duplicate_replay", "reversed_arrival", "deployed_table_equality"],
            "limitations": ["Bounded batch recomputation; incremental streaming CDC was not tested."],
        }
    )
)
