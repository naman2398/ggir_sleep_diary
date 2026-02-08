"""
Convert a long-format sleep diary CSV into a GGIR advanced sleeplog CSV.

Source format:  SUBJECT, Out_Bed, In_Bed  (one row per sleep episode)
Output format:  ID, D1_date, D1_wakeup, D1_inbed, D2_date, D2_wakeup, D2_inbed, ...
                (one row per recording segment, calendar-date oriented)

GGIR advanced sleeplog definition (per calendar date):
    wakeup = time participant woke up THAT MORNING  (ends previous night's sleep)
    inbed  = time participant went to bed THAT EVENING (starts tonight's sleep)

If inbed time is after midnight (< noon_cutoff), it belongs to the PREVIOUS
evening's calendar date.  This handles midnight-crossing bedtimes regardless
of how the source date was stamped.

Segments config (JSON) allows splitting into multiple rows by date range,
each row keyed to an accelerometer recording file ID.

Reference: https://wadpac.github.io/GGIR/articles/chapter9_SleepFundamentalsGuiders.html
"""

import argparse
import json
import logging
from datetime import timedelta
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def sanitise_id(raw_id: str) -> str:
    """Strip characters that are invalid in filenames (e.g. '/')."""
    return raw_id.replace("/", "")


def calendar_date_for_inbed(dt: pd.Timestamp, noon_cutoff: int = 12) -> str:
    """Return the calendar date (YYYY-MM-DD) an In_Bed timestamp belongs to.

    If the clock time is before noon_cutoff, the person went to bed after
    midnight — assign to the previous evening's calendar date.
    """
    if dt.hour < noon_cutoff:
        return (dt - timedelta(days=1)).strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d")


def calendar_date_for_wakeup(dt: pd.Timestamp) -> str:
    """Return the calendar date (YYYY-MM-DD) a wakeup timestamp belongs to.

    Wakeup always happens on the morning of its own calendar date.
    """
    return dt.strftime("%Y-%m-%d")


def fmt_time(dt: pd.Timestamp) -> str:
    """Format a timestamp as HH:MM:SS (time-only)."""
    return dt.strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# Build calendar-date lookup from source rows
# ---------------------------------------------------------------------------

def build_calendar(df: pd.DataFrame, noon_cutoff: int = 12) -> dict[str, dict[str, str]]:
    """Scatter source rows into a dict keyed by calendar date.

    Returns {calendar_date_str: {"wakeup": "HH:MM:SS", "inbed": "HH:MM:SS"}}
    """
    calendar: dict[str, dict[str, str]] = {}

    for _, row in df.iterrows():
        out_dt = row["out_bed_dt"]   # wakeup
        in_dt = row["in_bed_dt"]     # inbed / onset

        # Place wakeup
        if pd.notna(out_dt):
            cal_date = calendar_date_for_wakeup(out_dt)
            entry = calendar.setdefault(cal_date, {})
            if "wakeup" not in entry:
                entry["wakeup"] = fmt_time(out_dt)
            else:
                logger.warning("Duplicate wakeup for %s — keeping earlier value", cal_date)

        # Place inbed
        if pd.notna(in_dt):
            cal_date = calendar_date_for_inbed(in_dt, noon_cutoff)
            entry = calendar.setdefault(cal_date, {})
            if "inbed" not in entry:
                entry["inbed"] = fmt_time(in_dt)
            else:
                logger.warning("Duplicate inbed for %s — keeping earlier value", cal_date)

    return calendar


# ---------------------------------------------------------------------------
# Build one wide-format row from a calendar dict and date range
# ---------------------------------------------------------------------------

def build_wide_row(
    segment_id: str,
    calendar: dict[str, dict[str, str]],
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[list[str], list[str]]:
    """Build header and values lists for one row of the advanced sleeplog.

    Parameters
    ----------
    segment_id : value for the ID column.
    calendar   : full calendar dict from build_calendar().
    start_date : inclusive start (YYYY-MM-DD).  None = no lower bound.
    end_date   : inclusive end   (YYYY-MM-DD).  None = no upper bound.

    Returns (header, values) — header includes "ID" prefix.
    """
    sorted_dates = sorted(calendar.keys())

    # Filter to date range
    if start_date:
        sorted_dates = [d for d in sorted_dates if d >= start_date]
    if end_date:
        sorted_dates = [d for d in sorted_dates if d <= end_date]

    header = ["ID"]
    values = [segment_id]

    for i, cal_date in enumerate(sorted_dates, start=1):
        entry = calendar[cal_date]
        header.extend([f"D{i}_date", f"D{i}_wakeup", f"D{i}_inbed"])
        values.extend([
            cal_date,
            entry.get("wakeup", ""),
            entry.get("inbed", ""),
        ])

    return header, values


# ---------------------------------------------------------------------------
# In-memory conversion (used by the Streamlit app)
# ---------------------------------------------------------------------------

def convert_sleeplog_in_memory(
    df: pd.DataFrame,
    segments: list[dict],
    noon_cutoff: int = 12,
    datetime_fmt: str = "%m/%d/%y %H:%M",
) -> pd.DataFrame:
    """Run the full conversion pipeline and return a DataFrame.

    Parameters
    ----------
    df           : source DataFrame with columns SUBJECT, Out_Bed, In_Bed.
    segments     : list of dicts, each with keys "id", "start_date", "end_date".
    noon_cutoff  : hour threshold for midnight-crossing logic.
    datetime_fmt : strftime format of source datetime strings.

    Returns
    -------
    pd.DataFrame with the GGIR advanced sleeplog wide format.
    """
    df = df.dropna(subset=["Out_Bed", "In_Bed"], how="all").reset_index(drop=True)
    if df.empty:
        raise ValueError("No usable rows in the uploaded CSV.")

    df["out_bed_dt"] = pd.to_datetime(df["Out_Bed"], format=datetime_fmt, errors="coerce")
    df["in_bed_dt"] = pd.to_datetime(df["In_Bed"], format=datetime_fmt, errors="coerce")

    calendar = build_calendar(df, noon_cutoff)

    rows: list[list[str]] = []
    max_cols = 0

    for seg in segments:
        header, values = build_wide_row(
            segment_id=seg["id"],
            calendar=calendar,
            start_date=seg.get("start_date"),
            end_date=seg.get("end_date"),
        )
        rows.append(values)
        max_cols = max(max_cols, len(values))

    # Pad shorter rows
    for row in rows:
        while len(row) < max_cols:
            row.append("")

    # Use the header from the longest row
    longest_header = max(
        (build_wide_row(s["id"], calendar, s.get("start_date"), s.get("end_date"))[0]
         for s in segments),
        key=len,
    )
    while len(longest_header) < max_cols:
        longest_header.append("")

    return pd.DataFrame(rows, columns=longest_header)


# ---------------------------------------------------------------------------
# File-based conversion (CLI usage)
# ---------------------------------------------------------------------------

def convert_sleepdiary_to_advanced(
    input_csv: str | Path,
    segments_json: str | Path | None = None,
    output_dir: str | Path | None = None,
    noon_cutoff: int = 12,
    datetime_fmt: str = "%m/%d/%y %H:%M",
) -> Path:
    """Read a sleep diary CSV and write a GGIR advanced sleeplog CSV.

    Parameters
    ----------
    input_csv     : path to source CSV (columns: SUBJECT, Out_Bed, In_Bed).
    segments_json : path to JSON file defining recording segments.  Each entry:
                    {"id": "...", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}
                    If None, all data goes into one row with the sanitised SUBJECT id.
    output_dir    : directory for the output file (defaults to same as input).
    noon_cutoff   : hour threshold to decide if an In_Bed time belongs
                    to the previous calendar date.  Default 12 (noon).
    datetime_fmt  : strftime format of the source datetime strings.

    Returns
    -------
    Path to the generated advanced sleeplog CSV.
    """
    input_csv = Path(input_csv)
    output_dir = Path(output_dir) if output_dir else input_csv.parent

    # --- 1. Read & parse ------------------------------------------------
    df = pd.read_csv(input_csv, dtype={"SUBJECT": str})
    df = df.dropna(subset=["Out_Bed", "In_Bed"], how="all").reset_index(drop=True)

    if df.empty:
        raise ValueError(f"No usable rows in {input_csv}")

    participant_id = sanitise_id(df["SUBJECT"].iloc[0].strip())

    df["out_bed_dt"] = pd.to_datetime(df["Out_Bed"], format=datetime_fmt, errors="coerce")
    df["in_bed_dt"] = pd.to_datetime(df["In_Bed"], format=datetime_fmt, errors="coerce")

    logger.info(
        "Parsed %d rows for %s  (date range: %s – %s)",
        len(df), participant_id,
        df[["out_bed_dt", "in_bed_dt"]].min().min().date(),
        df[["out_bed_dt", "in_bed_dt"]].max().max().date(),
    )

    # --- 2. Scatter into calendar-date entries --------------------------
    calendar = build_calendar(df, noon_cutoff)
    logger.info("Calendar dates covered: %d", len(calendar))

    # --- 3. Load segments (or default to single row) --------------------
    if segments_json:
        with open(segments_json) as f:
            segments = json.load(f)
        logger.info("Loaded %d segments from %s", len(segments), segments_json)
    else:
        # Single row covering the full date range
        segments = [{"id": participant_id, "start_date": None, "end_date": None}]

    # --- 4. Build wide-format rows, one per segment --------------------
    rows: list[list[str]] = []
    max_cols = 0

    for seg in segments:
        header, values = build_wide_row(
            segment_id=seg["id"],
            calendar=calendar,
            start_date=seg.get("start_date"),
            end_date=seg.get("end_date"),
        )
        n_dates = (len(header) - 1) // 3
        logger.info("  Segment '%s': %d calendar dates", seg["id"], n_dates)
        rows.append(values)
        max_cols = max(max_cols, len(values))

    # Pad shorter rows so all rows share the same number of columns
    for row in rows:
        while len(row) < max_cols:
            row.append("")

    # Use the header from the longest row
    longest_header = max(
        (build_wide_row(s["id"], calendar, s.get("start_date"), s.get("end_date"))[0]
         for s in segments),
        key=len,
    )
    while len(longest_header) < max_cols:
        longest_header.append("")

    # --- 5. Write output ------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{participant_id}_sleeplog_advanced.csv"

    out_df = pd.DataFrame(rows, columns=longest_header)
    out_df.to_csv(output_path, index=False)

    logger.info("Written: %s  (%d rows, max %d calendar-date columns)",
                output_path, len(rows), (max_cols - 1) // 3)
    return output_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert a sleep diary CSV to GGIR advanced sleeplog format."
    )
    parser.add_argument("input_csv", help="Path to the source sleep diary CSV.")
    parser.add_argument(
        "-s", "--segments",
        default=None,
        help="Path to segments JSON file defining recording IDs and date ranges.",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=None,
        help="Output directory (default: same as input file).",
    )
    parser.add_argument(
        "--noon-cutoff",
        type=int,
        default=12,
        help="Hour cutoff for midnight-crossing logic (default: 12).",
    )
    parser.add_argument(
        "--datetime-fmt",
        default="%m/%d/%y %H:%M",
        help="strftime format of source datetime strings (default: '%%m/%%d/%%y %%H:%%M').",
    )

    args = parser.parse_args()
    convert_sleepdiary_to_advanced(
        args.input_csv,
        segments_json=args.segments,
        output_dir=args.output_dir,
        noon_cutoff=args.noon_cutoff,
        datetime_fmt=args.datetime_fmt,
    )
