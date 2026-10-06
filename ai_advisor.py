"""
AI Advisor — Tab-based planning tools.

Tabs:
  1. Capacity Calculator — pure math, no AI
  2. Timetable Generator — OR-Tools solver, multiple alternatives
"""

import math
import streamlit as st
import pandas as pd


# ============================================================
# TAB 1 — CAPACITY CALCULATOR (pure math)
# ============================================================

def capacity_calculator_tab():
    st.markdown("### 📊 Capacity Calculator")
    st.caption("Quick feasibility check — pure math, no AI involved.")

    col1, col2 = st.columns(2)
    with col1:
        teachers = st.number_input("Teachers", min_value=1, value=13, step=1, key="cc_teachers")
        classes = st.number_input("Classes", min_value=1, value=15, step=1, key="cc_classes")
        periods_per_day = st.number_input("Periods per day", min_value=1, value=8, step=1, key="cc_periods")
    with col2:
        days_per_week = st.number_input("Days per week", min_value=1, max_value=7, value=5, step=1, key="cc_days")
        periods_per_class = st.number_input("Periods per class per week", min_value=1, value=40, step=1, key="cc_ppc")
        max_periods_teacher = st.number_input("Max periods per teacher per week", min_value=1, value=30, step=1, key="cc_mpt")

    if st.button("Analyze Feasibility", type="primary", use_container_width=True, key="cc_analyze"):
        total_slots = periods_per_day * days_per_week
        demand = classes * periods_per_class
        capacity = teachers * max_periods_teacher
        teachers_needed = math.ceil(demand / max_periods_teacher) if max_periods_teacher else 0
        shortfall = max(0, demand - capacity)
        teachers_short = max(0, teachers_needed - teachers)
        avg_load = demand / teachers if teachers else 0

        st.divider()
        st.markdown("### Analysis Result")

        if demand <= capacity:
            st.success("✅ **Feasible** — you have enough teacher capacity.")
        else:
            st.error(f"❌ **Not feasible** — short by {shortfall} periods/week.")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Weekly Demand", f"{demand}")
        c2.metric("Weekly Capacity", f"{capacity}")
        c3.metric("Teachers Needed", f"{teachers_needed}")
        c4.metric("Avg Load/Teacher", f"{avg_load:.1f}")

        st.markdown("### 📋 Details")
        details = pd.DataFrame([
            {"Metric": "Total weekly slots per class", "Value": total_slots},
            {"Metric": "Periods per class per week", "Value": periods_per_class},
            {"Metric": "Total student-period demand", "Value": demand},
            {"Metric": "Teacher capacity", "Value": capacity},
            {"Metric": "Shortfall", "Value": shortfall},
            {"Metric": "Minimum teachers needed", "Value": teachers_needed},
            {"Metric": "Teachers short", "Value": teachers_short},
        ])
        st.dataframe(details, use_container_width=True, hide_index=True)

        if shortfall > 0:
            st.markdown("### 💡 Suggestions")
            st.info(
                f"**Option 1 — Add teachers**  \n"
                f"Add **{teachers_short}** more teachers to reach {teachers_needed}."
            )
            feasible_ppc = capacity // classes if classes else 0
            if feasible_ppc > 0:
                st.info(
                    f"**Option 2 — Reduce class periods**  \n"
                    f"Reduce to **{feasible_ppc}** periods/week per class (currently {periods_per_class})."
                )
            needed_daily = math.ceil(demand / (teachers * days_per_week)) if teachers and days_per_week else 0
            if needed_daily > periods_per_day:
                st.info(
                    f"**Option 3 — Add periods to the day**  \n"
                    f"Each teacher would need to teach **{needed_daily}** periods/day."
                )
        else:
            slack = capacity - demand
            st.success("No action needed — the setup is feasible.")
            st.info(f"You have **{slack}** periods/week of spare capacity.")


# ============================================================
# TAB 2 — TIMETABLE GENERATOR
# ============================================================

def timetable_generator_tab():
    st.markdown("### 📅 Timetable Generator")
    st.caption("Generates multiple alternative timetables from the school's data.")

      # Access the already-loaded app module (avoids circular import)
    import sys
    _app = sys.modules.get("app")
    if _app is None:
        st.error("App module not loaded. Please reload the page.")
        st.stop()

    tt_get_teachers = _app.tt_get_teachers
    tt_get_subjects = _app.tt_get_subjects
    tt_get_all_classes = _app.tt_get_all_classes
    tt_get_periods = _app.tt_get_periods
    tt_generate_timetable = _app.tt_generate_timetable

    try:
        teachers = tt_get_teachers()
        subjects = tt_get_subjects()
        classes = tt_get_all_classes()
        periods, breaks = tt_get_periods()
    except Exception as e:
        st.error(f"Could not read setup data: {e}")
        st.stop()

    st.markdown("#### Current Setup Detected")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Teachers", len(teachers))
    c2.metric("Classes", len(classes))
    c3.metric("Subjects", len(subjects))
    c4.metric("Periods/Day", len(periods))

    missing = []
    if not teachers:
        missing.append("Teachers")
    if not subjects:
        missing.append("Subjects")
    if not classes:
        missing.append("Classes")
    if not periods:
        missing.append("Periods")

    if missing:
        st.warning(
            "⚠️ Missing setup data: " + ", ".join(missing) + ".\n\n"
            "Please set up the school's timetable in "
            "**Settings → ⚙️ Timetable Setup** first."
        )
        st.stop()

    st.success("✅ All setup data present. Ready to generate.")

    st.divider()
    st.markdown("#### Generator Controls")

    g1, g2 = st.columns(2)
    with g1:
        n_alts = st.selectbox(
            "Number of alternatives",
            [1, 3, 5, 10],
            index=2,
            key="gen_nalts",
        )
    with g2:
        optimization = st.selectbox(
            "Optimization",
            ["Balanced"],
            key="gen_opt",
            help="More options coming soon.",
        )

    if st.button("🔄 Generate Timetables", type="primary", use_container_width=True, key="gen_go"):
        st.info(
            "ℹ️ This runs the solver multiple times. Each run may take up to 60 seconds. "
            f"You chose **{n_alts}** alternative(s), so this may take a few minutes."
        )

        progress = st.progress(0.0, text="Starting...")
        results = []

        for i in range(n_alts):
            progress.progress((i) / n_alts, text=f"Running solver {i+1}/{n_alts}...")
            try:
                result = tt_generate_timetable(max_seconds=60)
                if result.get("success"):
                    results.append({
                        "Alternative": i + 1,
                        "Status": "✅ Success",
                        "Slots": result.get("stats", {}).get("slots", 0),
                        "Time (s)": result.get("stats", {}).get("wall_time", 0),
                        "Message": result.get("message", "")[:60],
                    })
                else:
                    results.append({
                        "Alternative": i + 1,
                        "Status": "❌ Failed",
                        "Slots": 0,
                        "Time (s)": 0,
                        "Message": result.get("message", "unknown")[:60],
                    })
            except Exception as e:
                results.append({
                    "Alternative": i + 1,
                    "Status": "❌ Error",
                    "Slots": 0,
                    "Time (s)": 0,
                    "Message": str(e)[:60],
                })

        progress.progress(1.0, text="Complete.")

        st.markdown("#### Generation Results")
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

        successes = sum(1 for r in results if r["Status"].startswith("✅"))
        if successes > 0:
            st.success(f"Generated {successes} of {n_alts} alternatives successfully.")
            st.info(
                "📥 To view the timetable, go to **📅 Timetable** → **View Timetable**. "
                "The most recent successful run is what's stored."
            )
            st.caption(
                "Note: Storing multiple alternatives side-by-side is coming soon. "
                "For now, run them one at a time and download each PDF."
            )
        else:
            st.error("No timetables were generated. Check the setup and try again.")


# ============================================================
# MAIN RENDER
# ============================================================

def render_ai_advisor():
    st.subheader("🤖 AI Advisor")
    st.caption(
        "Plan capacity and generate timetable alternatives — "
        "all without exposing student data."
    )

    tab1, tab2 = st.tabs([
        "📊 Capacity Calculator",
        "📅 Timetable Generator",
    ])

    with tab1:
        capacity_calculator_tab()

    with tab2:
        timetable_generator_tab()
