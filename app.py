"""
GGIR Sleep Diary Converter — Streamlit Web Application

Upload a sleep diary CSV (SUBJECT, Out_Bed, In_Bed), define accelerometer
recording segments on the fly, and convert to GGIR advanced sleeplog format.
"""

import io
import json

import pandas as pd
import streamlit as st

from convert_sleeplog import convert_sleeplog_in_memory, sanitise_id

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="GGIR Sleep Diary Converter",
    page_icon="",
    layout="wide",
)

st.title("GGIR Sleep Diary Converter")
st.markdown(
    "Convert a long-format sleep diary CSV into the "
    "[GGIR advanced sleeplog](https://wadpac.github.io/GGIR/articles/"
    "chapter9_SleepFundamentalsGuiders.html) wide format."
)

# ── Session state init ───────────────────────────────────────────────────────
if "segments" not in st.session_state:
    st.session_state.segments = []

# ── Upload & settings ────────────────────────────────────────────────────────
uploaded_file = st.file_uploader(
    "Upload Sleep Diary CSV",
    type=["csv"],
    help="CSV with columns: SUBJECT, Out_Bed, In_Bed",
)

noon_cutoff = 12
datetime_fmt = "%m/%d/%y %H:%M"

# ── Preview uploaded file ────────────────────────────────────────────────────
if uploaded_file is not None:
    try:
        raw_df = pd.read_csv(uploaded_file, dtype={"SUBJECT": str})
        uploaded_file.seek(0)  # reset for re-read later
    except Exception as e:
        st.error(f"Failed to read CSV: {e}")
        st.stop()

    required_cols = {"SUBJECT", "Out_Bed", "In_Bed"}
    if not required_cols.issubset(raw_df.columns):
        st.error(
            f"CSV must contain columns: {', '.join(sorted(required_cols))}. "
            f"Found: {', '.join(raw_df.columns.tolist())}"
        )
        st.stop()

    with st.expander("📄 Preview uploaded sleep diary", expanded=False):
        st.dataframe(raw_df, use_container_width=True, height=300)

    participant_id = raw_df["SUBJECT"].dropna().iloc[0].strip()
    st.info(f"**Participant:** `{participant_id}`")

    # ── Segment builder ──────────────────────────────────────────────────
    st.header("Define Data Segments")
    st.markdown(
        "Each segment/file corresponds to an accelerometer recording file. "
        "Provide the **file name** (e.g., the `.GT3X` filename) and the "
        "**date range** it covers."
    )

    # --- Add new segment form ---
    with st.form("add_segment_form", clear_on_submit=True):
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            seg_id = st.text_input(
                "File Name",
                placeholder="e.g. AK/2509081926_STM2E24245506_2025-10-02_..._1.GT3X",
            )
        with col2:
            seg_start = st.date_input("Start date", value=None)
        with col3:
            seg_end = st.date_input("End date", value=None)

        submitted = st.form_submit_button("➕ Add Segment", use_container_width=True)
        if submitted:
            if not seg_id.strip():
                st.warning("File name cannot be empty.")
            elif seg_start is None or seg_end is None:
                st.warning("Please select both a start date and an end date.")
            elif seg_start > seg_end:
                st.warning("Start date must be before end date.")
            else:
                st.session_state.segments.append(
                    {
                        "id": seg_id.strip(),
                        "start_date": seg_start.isoformat(),
                        "end_date": seg_end.isoformat(),
                    }
                )
                st.success(f"Added segment: **{seg_id.strip()}**")

    # --- Show current segments ---
    if st.session_state.segments:
        st.subheader(f"Segments ({len(st.session_state.segments)})")

        for i, seg in enumerate(st.session_state.segments):
            col_info, col_del = st.columns([5, 1])
            with col_info:
                st.markdown(
                    f"**{i + 1}.** `{seg['id']}`  \n"
                    f"&emsp;📅 {seg['start_date']} → {seg['end_date']}"
                )
            with col_del:
                if st.button("🗑️", key=f"del_{i}", help="Remove this segment"):
                    st.session_state.segments.pop(i)
                    st.rerun()

        # --- Clear all segments ---
        if st.button("🧹 Clear all segments"):
            st.session_state.segments = []
            st.rerun()

    else:
        st.info("No segments defined yet. Add at least one segment above.")

    # ── Convert ──────────────────────────────────────────────────────────
    st.divider()
    st.header("Convert")

    if not st.session_state.segments:
        st.warning("Add at least one segment before converting.")
    else:
        if st.button("Convert to GGIR Advanced Sleeplog", type="primary", use_container_width=True):
            try:
                source_df = pd.read_csv(uploaded_file, dtype={"SUBJECT": str})
                uploaded_file.seek(0)

                result_df = convert_sleeplog_in_memory(
                    df=source_df,
                    segments=st.session_state.segments,
                    noon_cutoff=noon_cutoff,
                    datetime_fmt=datetime_fmt,
                )

                st.session_state.result_df = result_df
                st.success(
                    f"✅ Conversion complete — {len(result_df)} segment row(s), "
                    f"{(len(result_df.columns) - 1) // 3} max calendar-date columns."
                )
            except Exception as e:
                st.error(f"Conversion failed: {e}")

    # ── Results ──────────────────────────────────────────────────────────
    if "result_df" in st.session_state and st.session_state.result_df is not None:
        st.header("Result")
        st.dataframe(st.session_state.result_df, use_container_width=True)

        # Build filename
        safe_id = sanitise_id(participant_id)
        csv_buffer = io.StringIO()
        st.session_state.result_df.to_csv(csv_buffer, index=False)

        st.download_button(
            "⬇️ Download Advanced Sleeplog CSV",
            data=csv_buffer.getvalue(),
            file_name=f"{safe_id}_sleeplog_advanced.csv",
            mime="text/csv",
            type="primary",
        )

else:
    st.info("☝️ Upload a sleep diary CSV above to get started.")
