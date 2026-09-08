# Databricks notebook source
# MAGIC %md
# MAGIC ## Gold: component features, fault events, RUL labels
# MAGIC Builds rolling per-component feature tables (`gold.gearbox_features`, `gold.hydraulics_features`,
# MAGIC `gold.pitch_features`, `gold.generator_features`, `gold.transformer_features`,
# MAGIC `gold.rotor_brake_features`), a fleet-wide `gold.fault_events` table, and `gold.rul_labels`.
# MAGIC Sensor columns differ per farm (Farm B/C are anonymized `sensor_N`), so components are
# MAGIC resolved per farm by keyword-matching each farm's `feature_description.csv` `description`
# MAGIC column rather than hardcoding sensor names.

# COMMAND ----------

dbutils.widgets.text("env", "dev", "Target environment (dev/staging/uat)")
dbutils.widgets.text(
    "feature_description_root",
    "s3://dev-wtb-bronze/reference/feature_description/",
    "Root path containing farm=A/B/C feature_description.csv files",
)
dbutils.widgets.text("rul_horizon_hours", "720", "Max look-back horizon for RUL labels (hours)")

env = dbutils.widgets.get("env")
feature_description_root = dbutils.widgets.get("feature_description_root")
rul_horizon_hours = int(dbutils.widgets.get("rul_horizon_hours"))

catalog = env
gold_schema = "gold"
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{gold_schema}")

FARMS = ["A", "B", "C"]

# COMMAND ----------

from pyspark.sql import functions as F, DataFrame
from pyspark.sql.window import Window
from functools import reduce

# component -> keywords matched (case-insensitive, substring) against feature_description.description
COMPONENT_KEYWORDS = {
    "gearbox": ["gear", "planetary bearing"],
    "hydraulics": ["hydraulic"],
    "pitch": ["pitch", "blade"],
    "generator": ["generator"],
    "transformer": ["transformer"],
    "rotor_brake": ["rotor brake", "brake"],
    # Broadband drive-train/tower/nacelle vibration sensors - condition
    # monitoring for bearing/drivetrain wear via overall vibration amplitude,
    # not gearbox/generator bearing *temperature* (already covered above).
    "vibration": ["vibration"],
}

# gold.fault_events category keywords, matched against event_description; first match wins
FAULT_CATEGORY_KEYWORDS = [
    ("gearbox", ["gearbox", "gear box"]),
    ("hydraulic", ["hydraulic"]),
    ("pitch", ["pitch"]),
    ("generator", ["generator"]),
    ("transformer", ["transformer"]),
    ("converter", ["converter", "inverter"]),
    ("yaw", ["yaw"]),
    ("plc_communication", ["plc", "communication"]),
    ("rotor_brake", ["rotor brake", "brake"]),
    # Lowest priority (see `reversed()` below) - "generator bearing failure"
    # still resolves to "generator", not "bearing".
    ("bearing", ["bearing", "lager"]),
]

ROLLING_WINDOWS_HOURS = [1, 6, 24]


def load_feature_description(farm: str):
    path = f"{feature_description_root}farm={farm}/comma_feature_description.csv"
    return spark.read.option("header", "true").csv(path)


def matching_base_sensors(feature_description_df, keywords) -> list:
    """Return base sensor_name values (e.g. 'sensor_12', 'wind_speed_3') whose description
    contains any of the given keywords. Raw columns are these names + suffix (_avg/_min/_max/_std)."""
    pattern = "|".join(keywords)
    rows = (
        feature_description_df
        .filter(F.lower(F.col("description")).rlike(pattern))
        .select("sensor_name")
        .distinct()
        .collect()
    )
    return [r["sensor_name"] for r in rows]


def resolve_component_columns(farm: str, component: str, available_columns: set) -> list:
    """Map a component's matched base sensor names onto actual _avg columns present in
    this farm's silver table (not every stat suffix exists for every sensor)."""
    fd = load_feature_description(farm)
    base_names = matching_base_sensors(fd, COMPONENT_KEYWORDS[component])
    resolved = []
    for base in base_names:
        avg_col = f"{base}_avg"
        if avg_col in available_columns:
            resolved.append(avg_col)
        elif base in available_columns:
            # some columns (e.g. counters) ship without a stat suffix
            resolved.append(base)
    return sorted(set(resolved))

# COMMAND ----------

# MAGIC %md ### Component feature tables: rolling 1h / 6h / 24h aggregates per farm, unioned per component

# COMMAND ----------

def build_component_features(component: str) -> DataFrame:
    per_farm_frames = []
    for farm in FARMS:
        silver_table = f"{catalog}.silver.farm_{farm.lower()}"
        if not spark.catalog.tableExists(silver_table):
            continue
        silver_df = spark.table(silver_table)
        sensor_cols = resolve_component_columns(farm, component, set(silver_df.columns))
        if not sensor_cols:
            continue

        # window ordered by time, ranged in seconds so it works across the three horizons
        base = silver_df.select(
            "farm", "asset_id", "time_stamp", "status_type_id", "event_id", "event_label", *sensor_cols
        )
        ts_seconds = F.col("time_stamp").cast("long")
        agg_exprs = []
        for hours in ROLLING_WINDOWS_HOURS:
            w = (
                Window.partitionBy("asset_id")
                .orderBy(ts_seconds)
                .rangeBetween(-hours * 3600, 0)
            )
            for c in sensor_cols:
                agg_exprs.append(F.avg(c).over(w).alias(f"{c}_avg_{hours}h"))
                agg_exprs.append(F.stddev(c).over(w).alias(f"{c}_std_{hours}h"))

        farm_features = base.select(
            "farm", "asset_id", "time_stamp", "status_type_id", "event_id", "event_label", *agg_exprs
        )
        per_farm_frames.append(farm_features)

    if not per_farm_frames:
        raise ValueError(f"no farm silver tables produced columns for component={component}")

    # column sets differ per farm (different sensor_cols matched), so union by name and let
    # missing columns fill as null rather than forcing a shared schema across farms.
    return reduce(lambda a, b: a.unionByName(b, allowMissingColumns=True), per_farm_frames)


for component in COMPONENT_KEYWORDS:
    table_name = f"{catalog}.{gold_schema}.{component}_features"
    features_df = build_component_features(component)
    (
        features_df.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .partitionBy("farm")
        .saveAsTable(table_name)
    )
    print(f"wrote {table_name}")

# COMMAND ----------

# MAGIC %md ### gold.fault_events: one row per labeled event, classified by keyword match on event_description

# COMMAND ----------

def classify_fault_category(description_col):
    expr = F.lit("other")
    for category, keywords in reversed(FAULT_CATEGORY_KEYWORDS):
        pattern = "|".join(keywords)
        expr = F.when(F.lower(description_col).rlike(pattern), F.lit(category)).otherwise(expr)
    return expr


fault_event_frames = []
for farm in FARMS:
    event_info_path = f"s3://{env}-wtb-bronze/farm={farm}/event_info/"
    try:
        event_info = spark.read.option("header", "true").csv(event_info_path)
    except Exception:
        continue
    farm_events = (
        event_info
        .filter(F.col("event_label") == "anomaly")
        .withColumn("farm", F.lit(farm))
        .withColumn("category", classify_fault_category(F.col("event_description")))
        .withColumn("event_start", F.to_utc_timestamp(F.to_timestamp("event_start"), "UTC"))
        .withColumn("event_end", F.to_utc_timestamp(F.to_timestamp("event_end"), "UTC"))
        .select("farm", "event_id", "category", "event_start", "event_end", "event_description")
    )
    fault_event_frames.append(farm_events)

if fault_event_frames:
    fault_events_df = reduce(lambda a, b: a.unionByName(b), fault_event_frames)
    # event_info has no asset_id column directly; attach it from silver rows tagged with this event
    asset_lookup_frames = []
    for farm in FARMS:
        silver_table = f"{catalog}.silver.farm_{farm.lower()}"
        if spark.catalog.tableExists(silver_table):
            asset_lookup_frames.append(
                spark.table(silver_table)
                .filter(F.col("event_id").isNotNull())
                .select("farm", "event_id", "asset_id")
                .distinct()
            )
    asset_lookup = reduce(lambda a, b: a.unionByName(b), asset_lookup_frames)

    fault_events_df = fault_events_df.join(asset_lookup, on=["farm", "event_id"], how="left")

    (
        fault_events_df.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(f"{catalog}.{gold_schema}.fault_events")
    )
    print(f"wrote {catalog}.{gold_schema}.fault_events")

# COMMAND ----------

# MAGIC %md ### gold.rul_labels: hours until event_start, per pre-event row, anomaly events only

# COMMAND ----------

rul_frames = []
for farm in FARMS:
    silver_table = f"{catalog}.silver.farm_{farm.lower()}"
    if not spark.catalog.tableExists(silver_table):
        continue
    silver_df = spark.table(silver_table)

    anomaly_events = (
        spark.table(f"{catalog}.{gold_schema}.fault_events")
        .filter(F.col("farm") == farm)
        .select(
            F.col("event_id").alias("fe_event_id"),
            F.col("asset_id").alias("fe_asset_id"),
            F.col("event_start").alias("fe_event_start"),
        )
    )

    # pre-event rows: same asset, timestamp strictly before that event's start and within the
    # RUL horizon, not already inside any event window (event_id is null on non-event silver rows)
    candidate = (
        silver_df.filter(F.col("event_id").isNull())
        .join(
            F.broadcast(anomaly_events),
            on=(F.col("asset_id") == F.col("fe_asset_id"))
            & (F.col("time_stamp") < F.col("fe_event_start")),
            how="inner",
        )
        .withColumn(
            "hours_to_failure",
            (F.col("fe_event_start").cast("long") - F.col("time_stamp").cast("long")) / 3600.0,
        )
        .filter(F.col("hours_to_failure") <= rul_horizon_hours)
    )

    # a row can precede several future anomaly events for the same asset; label against
    # the nearest one only (smallest hours_to_failure)
    nearest_window = Window.partitionBy("asset_id", "time_stamp").orderBy("hours_to_failure")
    pre_event = (
        candidate.withColumn("_rn", F.row_number().over(nearest_window))
        .filter(F.col("_rn") == 1)
        .select(
            F.lit(farm).alias("farm"),
            "asset_id",
            "time_stamp",
            F.col("fe_event_id").alias("event_id"),
            "hours_to_failure",
        )
    )
    rul_frames.append(pre_event)

if rul_frames:
    rul_labels_df = reduce(lambda a, b: a.unionByName(b), rul_frames)
    (
        rul_labels_df.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .partitionBy("farm")
        .saveAsTable(f"{catalog}.{gold_schema}.rul_labels")
    )
    print(f"wrote {catalog}.{gold_schema}.rul_labels")
