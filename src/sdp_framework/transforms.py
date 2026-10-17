"""Pure Spark DataFrame functions shared by SDP and workspace verification."""

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F


def clean_events(bronze: DataFrame) -> DataFrame:
    """Exclude quarantined rows and deduplicate validated event identities."""
    return (
        bronze.filter(F.col("invalid_reason").isNull())
        .dropDuplicates(["event_id"])
        .withColumn("event_time", F.to_timestamp("event_time"))
    )


def customer_history(silver: DataFrame) -> DataFrame:
    """Recompute full-feed history, suppressing unchanged images and preserving delete gaps."""
    order = Window.partitionBy("customer_id").orderBy("sequence")
    previous = silver.withColumns(
        {
            "previous_operation": F.lag("operation").over(order),
            "previous_name": F.lag("name").over(order),
            "previous_email": F.lag("email").over(order),
        }
    )
    unchanged = (
        (F.col("operation") == "UPSERT")
        & (F.col("previous_operation") == "UPSERT")
        & F.col("name").eqNullSafe(F.col("previous_name"))
        & F.col("email").eqNullSafe(F.col("previous_email"))
    )
    changes = previous.filter(~F.coalesce(unchanged, F.lit(False)))
    # Calculate the end boundary BEFORE filtering DELETEs, or deleted rows remain current.
    intervals = changes.withColumn("valid_to", F.lead("event_time").over(order))
    return intervals.filter(F.col("operation") == "UPSERT").select(
        "customer_id", "name", "email", F.col("event_time").alias("valid_from"), "valid_to"
    )
