"""Interactive dashboard for the Haldummulla landslide risk index."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from lslrsi.dashboard import RISK_CLASS_ORDER, load_dashboard_data

ROOT = Path(__file__).resolve().parent
TABLES = ROOT / "outputs" / "tables"
FIGURES = ROOT / "outputs" / "figures"
RISK_DATA = TABLES / "haldummulla_gn_risk_scores.csv"
METADATA = TABLES / "analysis_metadata.json"


st.set_page_config(
    page_title="Haldummulla Landslide Risk Index",
    page_icon="⛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(show_spinner=False)
def load_data(risk_version: int, metadata_version: int) -> tuple[pd.DataFrame, dict]:
    """Load generated assets; version arguments invalidate the cache after rebuilds."""
    del risk_version, metadata_version
    return load_dashboard_data(RISK_DATA, METADATA)


def format_score(value: float) -> str:
    """Format a dashboard score with one decimal place."""
    return f"{value:.1f}"


try:
    risk_data, metadata = load_data(
        RISK_DATA.stat().st_mtime_ns,
        METADATA.stat().st_mtime_ns,
    )
except (FileNotFoundError, OSError, UnicodeError, ValueError) as error:
    st.error(str(error))
    st.stop()


st.title("Haldummulla Location-Specific Landslide Risk Index")
st.caption(
    "Relative screening results for the Haldummulla Divisional Secretariat Division, "
    "Badulla District, Sri Lanka"
)

with st.sidebar:
    st.header("Explore the results")
    available_classes = set(risk_data["risk_class"].dropna().astype(str))
    risk_classes = ["All classes"] + [
        risk_class for risk_class in RISK_CLASS_ORDER if risk_class in available_classes
    ]
    selected_class = st.selectbox("Risk class", risk_classes)
    maximum_rows = st.slider(
        "Rows to display",
        min_value=1,
        max_value=len(risk_data),
        value=min(10, len(risk_data)),
    )
    st.download_button(
        "Download GN results",
        data=risk_data.to_csv(index=False).encode("utf-8"),
        file_name="haldummulla_gn_risk_scores.csv",
        mime="text/csv",
    )

filtered_data = risk_data.copy()
if selected_class != "All classes":
    filtered_data = filtered_data[filtered_data["risk_class"].eq(selected_class)]
display_data = filtered_data.sort_values("risk_rank").head(maximum_rows)

metric_columns = st.columns(4)
metric_columns[0].metric("GN divisions", f"{metadata['gn_divisions']:,}")
metric_columns[1].metric("Population", f"{metadata['population_2024_provisional']:,}")
metric_columns[2].metric("Study area", f"{metadata['study_area_km2']:.1f} km²")
metric_columns[3].metric("Top risk score", format_score(float(risk_data["risk_score"].max())))

st.subheader("Prioritisation overview")
chart_data = display_data.set_index("GND_Name")[
    ["risk_score", "susceptibility_score", "exposure_score"]
]
chart_data = chart_data.rename(
    columns={
        "risk_score": "Risk",
        "susceptibility_score": "Susceptibility",
        "exposure_score": "Exposure",
    }
)
st.bar_chart(chart_data)

table_columns = [
    "risk_rank",
    "GND_Name",
    "risk_class",
    "risk_score",
    "susceptibility_score",
    "exposure_score",
    "Population",
    "sensitivity_class_stability",
]
table = display_data[table_columns].rename(
    columns={
        "risk_rank": "Rank",
        "GND_Name": "GN division",
        "risk_class": "Class",
        "risk_score": "Risk score",
        "susceptibility_score": "Susceptibility",
        "exposure_score": "Exposure",
        "sensitivity_class_stability": "Class stability",
    }
)
for column in ["Risk score", "Susceptibility", "Exposure", "Class stability"]:
    table[column] = table[column].map(lambda value: f"{value:.3f}")
st.dataframe(table, hide_index=True, width="stretch")

st.subheader("Analysis figures")
figure_files = {
    "Study area and population": "figure_01_study_area_population.png",
    "Physical indicators": "figure_02_physical_indicators.png",
    "Indicator distributions": "figure_03_indicator_distributions.png",
    "Indicator correlation": "figure_04_indicator_correlation.png",
    "Susceptibility and events": "figure_05_susceptibility_and_events.png",
    "Final GN risk": "figure_06_final_gn_risk.png",
    "Top risk components": "figure_07_top_risk_components.png",
    "Weight sensitivity": "figure_08_weight_sensitivity.png",
    "Index workflow": "figure_09_index_workflow.png",
}
selected_figure = st.selectbox("Figure", list(figure_files))
figure_filename = figure_files[selected_figure]
figure_path = FIGURES / figure_filename
if figure_path.exists():
    st.image(str(figure_path), width="stretch")
else:
    st.warning(f"Figure is not available: {figure_filename}")

with st.expander("Method and intended use"):
    st.write(
        "The index combines a 30 m physical susceptibility surface with GN-level "
        "social exposure. Susceptibility uses slope, rainfall, land cover, local "
        "relief, clay, road proximity and stream proximity. Exposure uses population "
        "density, occupied housing density, vulnerable population share and critical "
        "amenity density. Final risk is a weighted geometric mean with 70% "
        "susceptibility and 30% exposure."
    )
    st.write(
        "These are relative screening scores for prioritisation. They are not "
        "engineering design, cadastral decisions or operational early-warning thresholds."
    )
    sensitivity = metadata["sensitivity_rank_correlation"]
    st.write(
        f"The {sensitivity['iterations']}-iteration weight sensitivity test produced "
        f"a median Spearman rank correlation of {sensitivity['median']:.3f}."
    )

st.caption("Data and methodology are available in DATA_SOURCES.md and README.md in the repository.")
