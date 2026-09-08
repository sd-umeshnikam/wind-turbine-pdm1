"""01 - Data quality profiling for the wind-turbine SCADA fleet.

Per farm (A, B, C):
  - file count, row count, column count
  - missingness % per column, bucketed into always/mostly/sparse populated
    (not printed column-by-column for 900+ column farms - see outputs json
    for the full per-column breakdown)
  - dtype sanity (expected vs actual dtype per metadata column, plus a check
    that every sensor column parses as numeric)
  - status_type_id distribution (counts + %) per farm
  - train_test split distribution per farm
  - a check that every file in a farm shares the same column schema

Farm C (958 cols, 17GB total) is read one file at a time with the fast
'pyarrow' CSV engine (~2-3s / 300MB file, ~400MB resident per file) so peak
memory stays bounded to a single file rather than the whole farm.

Run:
    python eda/scripts/01_data_quality.py
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    FARMS,
    FARM_META,
    STATUS_TYPE_LABELS,
    dataset_files,
    ensure_output_dirs,
    hr,
    OUTPUTS_DIR,
)

MOSTLY_POPULATED_THRESHOLD_PCT = 5.0  # <= this % missing => "mostly populated"

EXPECTED_META_DTYPES = {
    "time_stamp": "datetime",
    "asset_id": "int",
    "id": "int",
    "train_test": "str",
    "status_type_id": "int",
}


def _dtype_bucket(dtype) -> str:
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime"
    if pd.api.types.is_integer_dtype(dtype):
        return "int"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    return "str"


def profile_farm(farm: str) -> dict:
    files = dataset_files(farm)
    n_files = len(files)
    print(f"  {n_files} files found")

    total_rows = 0
    null_sum: pd.Series | None = None
    dtype_by_col: dict[str, str] = {}
    dtype_mismatches: list[str] = []
    reference_columns: list[str] | None = None
    schema_mismatched_files: list[str] = []
    status_counter: Counter = Counter()
    traintest_counter: Counter = Counter()
    per_file_rows: dict[str, int] = {}
    status_out_of_range: list[str] = []

    t0 = time.time()
    for i, fp in enumerate(files, 1):
        df = pd.read_csv(fp, engine="pyarrow")
        n = len(df)
        total_rows += n
        per_file_rows[fp.name] = n

        cols = list(df.columns)
        if reference_columns is None:
            reference_columns = cols
        elif cols != reference_columns:
            schema_mismatched_files.append(fp.name)

        nulls = df.isna().sum()
        null_sum = nulls if null_sum is None else null_sum.add(nulls, fill_value=0)

        for col in cols:
            bucket = _dtype_bucket(df[col].dtype)
            if col not in dtype_by_col:
                dtype_by_col[col] = bucket
            elif dtype_by_col[col] != bucket:
                dtype_mismatches.append(f"{col} (file {fp.name}: {bucket} vs {dtype_by_col[col]})")

        if "status_type_id" in df.columns:
            status_counter.update(df["status_type_id"].dropna().astype(int).tolist())
            bad = df.loc[~df["status_type_id"].isin(STATUS_TYPE_LABELS.keys()), "status_type_id"]
            if len(bad):
                status_out_of_range.append(f"{fp.name}: {bad.unique().tolist()}")
        if "train_test" in df.columns:
            traintest_counter.update(df["train_test"].dropna().astype(str).tolist())

        del df
        if i % 10 == 0 or i == n_files:
            print(f"    processed {i}/{n_files} files ({time.time() - t0:.1f}s elapsed)")

    elapsed = time.time() - t0
    n_cols = len(reference_columns) if reference_columns else 0

    # --- missingness bucketing ---------------------------------------------
    always_populated, mostly_populated, sparse = [], [], []
    missingness_pct: dict[str, float] = {}
    if null_sum is not None and total_rows > 0:
        for col in reference_columns:
            pct = float(null_sum.get(col, 0)) / total_rows * 100.0
            missingness_pct[col] = round(pct, 4)
            if pct == 0:
                always_populated.append(col)
            elif pct <= MOSTLY_POPULATED_THRESHOLD_PCT:
                mostly_populated.append(col)
            else:
                sparse.append(col)

    # --- expected metadata dtype sanity -------------------------------------
    meta_dtype_check = {}
    for col, expected in EXPECTED_META_DTYPES.items():
        actual = dtype_by_col.get(col, "MISSING")
        meta_dtype_check[col] = {"expected": expected, "actual": actual, "ok": actual == expected}

    status_dist = {
        int(k): {
            "label": STATUS_TYPE_LABELS.get(int(k), "unknown"),
            "count": int(v),
            "pct": round(v / total_rows * 100.0, 3) if total_rows else 0.0,
        }
        for k, v in sorted(status_counter.items())
    }
    traintest_dist = {
        k: {"count": int(v), "pct": round(v / total_rows * 100.0, 3) if total_rows else 0.0}
        for k, v in sorted(traintest_counter.items())
    }

    result = {
        "farm": farm,
        "label": FARM_META[farm]["label"],
        "n_files": n_files,
        "n_columns": n_cols,
        "n_rows_total": total_rows,
        "avg_rows_per_file": round(total_rows / n_files, 1) if n_files else 0,
        "read_time_sec": round(elapsed, 1),
        "schema_consistent_across_files": len(schema_mismatched_files) == 0,
        "schema_mismatched_files": schema_mismatched_files,
        "missingness_summary": {
            "always_populated_count": len(always_populated),
            "mostly_populated_count": len(mostly_populated),
            "sparse_count": len(sparse),
            "mostly_populated_threshold_pct": MOSTLY_POPULATED_THRESHOLD_PCT,
            "sparse_columns": {c: missingness_pct[c] for c in sparse},
            "mostly_populated_columns": {c: missingness_pct[c] for c in mostly_populated},
        },
        "dtype_sanity": {
            "metadata_columns": meta_dtype_check,
            "dtype_mismatches_across_files": dtype_mismatches[:50],
            "n_dtype_mismatches": len(dtype_mismatches),
        },
        "status_type_id_distribution": status_dist,
        "status_type_id_out_of_range_files": status_out_of_range,
        "train_test_distribution": traintest_dist,
        "per_file_row_counts": per_file_rows,
    }
    return result


def print_human_summary(all_results: dict) -> None:
    hr("DATA QUALITY SUMMARY")
    for farm in FARMS:
        r = all_results[farm]
        print(f"\n--- {r['label']} ---")
        print(f"Files: {r['n_files']}   Columns: {r['n_columns']}   Total rows: {r['n_rows_total']:,}"
              f"   (avg {r['avg_rows_per_file']:,.0f} rows/file)")
        print(f"Schema consistent across files: {r['schema_consistent_across_files']}"
              + (f"  MISMATCHES: {r['schema_mismatched_files']}" if r['schema_mismatched_files'] else ""))
        ms = r["missingness_summary"]
        print(f"Missingness buckets -> always populated: {ms['always_populated_count']}, "
              f"mostly populated (<= {ms['mostly_populated_threshold_pct']}% missing): {ms['mostly_populated_count']}, "
              f"sparse (> {ms['mostly_populated_threshold_pct']}% missing): {ms['sparse_count']}")
        if ms["sparse_columns"]:
            top_sparse = sorted(ms["sparse_columns"].items(), key=lambda kv: -kv[1])[:8]
            print(f"  Sparsest columns (top 8): {top_sparse}")
        ds = r["dtype_sanity"]
        bad_meta = [c for c, v in ds["metadata_columns"].items() if not v["ok"]]
        print(f"Metadata dtype sanity: {'OK' if not bad_meta else 'ISSUES in ' + str(bad_meta)}")
        print(f"Cross-file dtype mismatches: {ds['n_dtype_mismatches']}")
        print("status_type_id distribution:")
        for sid, info in r["status_type_id_distribution"].items():
            print(f"    {sid} ({info['label']}): {info['count']:,} rows ({info['pct']}%)")
        if r["status_type_id_out_of_range_files"]:
            print(f"  ! out-of-range status_type_id values found in: {r['status_type_id_out_of_range_files']}")
        print("train_test distribution:")
        for k, info in r["train_test_distribution"].items():
            print(f"    {k}: {info['count']:,} rows ({info['pct']}%)")


def main() -> None:
    ensure_output_dirs()
    all_results = {}
    for farm in FARMS:
        hr(f"Profiling {FARM_META[farm]['label']}")
        all_results[farm] = profile_farm(farm)

    out_path = OUTPUTS_DIR / "data_quality.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved machine-readable results to {out_path}")

    print_human_summary(all_results)


if __name__ == "__main__":
    main()
