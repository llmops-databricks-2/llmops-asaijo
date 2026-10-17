"""Generated fixed-pattern SDP starter; deploy only after architecture review."""

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from sdp_framework.transforms import clean_events, customer_history

spark = SparkSession.builder.getOrCreate()


@dp.materialized_view(name="sdp_bronze_customers")
def bronze_customers() -> DataFrame:
    """Read the complete mock feed prepared by the job."""
    return spark.read.table(spark.conf.get("sdp.source_table"))


@dp.materialized_view(name="sdp_customer_quarantine")
def quarantine() -> DataFrame:
    """Retain invalid inputs for review."""
    return spark.read.table("sdp_bronze_customers").filter(F.col("invalid_reason").isNotNull())


@dp.materialized_view(name="sdp_silver_customers")
@dp.expect_or_fail("valid_key", "customer_id IS NOT NULL AND length(customer_id) > 0")
@dp.expect_or_fail("valid_time", "event_time IS NOT NULL")
def silver_customers() -> DataFrame:
    """Normalize event time and suppress duplicate event IDs."""
    return clean_events(spark.read.table("sdp_bronze_customers"))


@dp.materialized_view(name="sdp_gold_customer_history")
@dp.expect_or_fail("positive_interval", "valid_to IS NULL OR valid_from < valid_to")
def gold_customer_history() -> DataFrame:
    """Preserve customer changes and close deleted records."""
    return customer_history(spark.read.table("sdp_silver_customers"))
