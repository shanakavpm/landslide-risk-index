"""Report-figure generation for the LS-LRSI workflow."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.font_manager import FontProperties
from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402


def add_map_aids(axis, scale_length_m: float = 5_000) -> None:
    """Add a compact north arrow and metric scale bar to a projected map."""
    axis.annotate(
        "N",
        xy=(0.96, 0.96),
        xytext=(0.96, 0.88),
        xycoords="axes fraction",
        textcoords="axes fraction",
        ha="center",
        va="center",
        fontsize=9,
        fontweight="bold",
        arrowprops={"arrowstyle": "-|>", "color": "#222222", "lw": 1.2},
    )
    scale_bar = AnchoredSizeBar(
        axis.transData,
        scale_length_m,
        f"{scale_length_m / 1000:g} km",
        "lower right",
        pad=0.35,
        color="#222222",
        frameon=True,
        size_vertical=35,
        fontproperties=FontProperties(size=8),
    )
    axis.add_artist(scale_bar)


def plot_raster(
    axis,
    array: np.ndarray,
    transform,
    title: str,
    cmap: str = "viridis",
    label: str | None = None,
    boundaries: gpd.GeoDataFrame | None = None,
) -> None:
    """Plot one georeferenced array with optional polygon boundaries."""
    extent = [
        transform.c,
        transform.c + transform.a * array.shape[1],
        transform.f + transform.e * array.shape[0],
        transform.f,
    ]
    image = axis.imshow(array, extent=extent, origin="upper", cmap=cmap)
    if boundaries is not None:
        boundaries.boundary.plot(
            ax=axis,
            color="black",
            linewidth=0.25,
            alpha=0.65,
        )
    axis.set_title(title, fontsize=10)
    axis.set_xlabel("Easting (m)")
    axis.set_ylabel("Northing (m)")
    colorbar = plt.colorbar(image, ax=axis, shrink=0.78)
    if label:
        colorbar.set_label(label)
    add_map_aids(axis)


def add_source_note(figure, note: str) -> None:
    """Add a small source note at the bottom of a figure."""
    figure.text(0.01, 0.005, note, fontsize=7, color="#444444")


def create_analysis_figures(
    *,
    figures: Path,
    tables: Path,
    gns: gpd.GeoDataFrame,
    transform,
    slope: np.ndarray,
    rainfall: np.ndarray,
    local_relief: np.ndarray,
    landcover_risk: np.ndarray,
    clay_percent: np.ndarray,
    indicators: dict[str, np.ndarray],
    raster_bounds: dict[str, dict[str, float]],
    susceptibility: np.ndarray,
    candidates: gpd.GeoDataFrame,
    class_labels: list[str],
    random_generator: np.random.Generator,
    sensitivity_draws: np.ndarray,
    division_name: str,
    analysis_crs: str,
) -> None:
    """Create the nine figures and the sampled indicator-correlation table."""
    sns.set_theme(style="whitegrid", context="notebook")

    figure, axis = plt.subplots(figsize=(9, 8))
    gns.plot(
        column="population_density_km2",
        cmap="YlOrRd",
        linewidth=0.5,
        edgecolor="white",
        legend=True,
        legend_kwds={"label": "Population density (people/km²)", "shrink": 0.78},
        ax=axis,
    )
    gns.boundary.plot(ax=axis, color="#333333", linewidth=0.35)
    axis.set_title(f"{division_name} DSD: 2024 population density by GN division")
    axis.set_xlabel("Easting (m)")
    axis.set_ylabel("Northing (m)")
    add_map_aids(axis)
    add_source_note(
        figure,
        f"Sources: Sri Lanka DCS CPH 2024 provisional GN data and boundaries. CRS: {analysis_crs}.",
    )
    figure.tight_layout(rect=(0, 0.025, 1, 1))
    figure.savefig(figures / "figure_01_study_area_population.png", dpi=220)
    plt.close(figure)

    figure, axes = plt.subplots(2, 2, figsize=(13, 10))
    plot_raster(axes[0, 0], slope, transform, "Slope", "magma", "degrees", gns)
    plot_raster(
        axes[0, 1],
        rainfall,
        transform,
        "Mean annual rainfall, 1981–2024",
        "Blues",
        "mm/year",
        gns,
    )
    plot_raster(
        axes[1, 0],
        landcover_risk,
        transform,
        "Land-cover contribution",
        "YlOrBr",
        "risk value (0–1)",
        gns,
    )
    plot_raster(
        axes[1, 1],
        clay_percent,
        transform,
        "Topsoil clay (0–5 cm)",
        "copper",
        "% by mass",
        gns,
    )
    figure.suptitle("Selected landslide susceptibility indicators", fontsize=14)
    add_source_note(
        figure,
        "Sources: Copernicus DEM GLO-30; CHIRPS v2.0; ESA WorldCover 2021 v200; SoilGrids 2.0.",
    )
    figure.tight_layout(rect=(0, 0.025, 1, 0.97))
    figure.savefig(figures / "figure_02_physical_indicators.png", dpi=220)
    plt.close(figure)

    distribution_layers = [
        ("Slope", slope, "degrees", "#7B2CBF", "slope"),
        ("Mean annual rainfall", rainfall, "mm/year", "#277DA1", "rainfall"),
        ("Local relief (1 km)", local_relief, "m", "#F8961E", "local_relief"),
        ("Topsoil clay (0–5 cm)", clay_percent, "% by mass", "#8C5A3C", "clay"),
    ]
    figure, axes = plt.subplots(2, 2, figsize=(10.5, 6.6), constrained_layout=True)
    for axis, (title, array, unit, color, indicator_name) in zip(
        axes.flat, distribution_layers, strict=False
    ):
        values = array[np.isfinite(array)]
        bounds = raster_bounds[indicator_name]
        axis.hist(
            values,
            bins=45,
            color=color,
            alpha=0.82,
            edgecolor="white",
            linewidth=0.25,
        )
        axis.axvline(
            bounds["p02"],
            color="#1F4E79",
            linestyle="--",
            linewidth=1.5,
            label=f"P2 = {bounds['p02']:,.2f}",
        )
        axis.axvline(
            bounds["p98"],
            color="#C43C39",
            linestyle="--",
            linewidth=1.5,
            label=f"P98 = {bounds['p98']:,.2f}",
        )
        axis.set_title(title, fontsize=11, fontweight="bold")
        axis.set_xlabel(unit, fontsize=9)
        axis.set_ylabel("Valid cells", fontsize=9)
        axis.tick_params(labelsize=8)
        axis.grid(axis="y", alpha=0.22, linewidth=0.6)
        axis.legend(frameon=False, fontsize=8, loc="upper right")
        for spine in ("top", "right"):
            axis.spines[spine].set_visible(False)
    figure.suptitle(
        "Indicator distributions and robust P2–P98 scaling bounds",
        fontsize=13,
        fontweight="bold",
    )
    add_source_note(
        figure,
        "Source: Author's calculations from valid cells in the harmonised 30 m analysis rasters.",
    )
    figure.savefig(
        figures / "figure_03_indicator_distributions.png",
        dpi=260,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(figure)

    valid_indices = np.flatnonzero(np.isfinite(susceptibility))
    sample_size = min(30_000, valid_indices.size)
    sample = random_generator.choice(valid_indices, size=sample_size, replace=False)
    correlation_data = pd.DataFrame(
        {name: array.ravel()[sample] for name, array in indicators.items()}
    ).dropna()
    correlation = correlation_data.corr(method="spearman")
    correlation.to_csv(tables / "indicator_spearman_correlation.csv")
    figure, axis = plt.subplots(figsize=(9, 7))
    sns.heatmap(
        correlation,
        annot=True,
        fmt=".2f",
        cmap="vlag",
        center=0,
        square=True,
        ax=axis,
    )
    axis.set_title(
        "Spearman correlation of normalized indicators "
        f"(random sample, n={len(correlation_data):,})"
    )
    add_source_note(
        figure,
        "Source: Author's calculations from the seven verified and normalized project indicators.",
    )
    figure.tight_layout(rect=(0, 0.025, 1, 1))
    figure.savefig(figures / "figure_04_indicator_correlation.png", dpi=220)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(10, 8))
    plot_raster(
        axis,
        susceptibility,
        transform,
        "30 m landslide susceptibility index",
        "RdYlGn_r",
        "score (0–100)",
        gns,
    )
    inside_candidates = candidates[candidates["inside_study_area"]].copy()
    if not inside_candidates.empty:
        inside_candidates.plot(
            ax=axis,
            marker="*",
            color="#00ffff",
            edgecolor="black",
            markersize=110,
            label="NASA candidate inside DSD",
        )
        axis.legend(loc="lower left")
    add_source_note(
        figure,
        "Sources: Derived susceptibility from the verified project inputs; NASA GLC event "
        f"check ({len(inside_candidates)} of {len(candidates)} keyword candidates inside the DSD; "
        "stated accuracy 1-10 km).",
    )
    figure.tight_layout(rect=(0, 0.025, 1, 1))
    figure.savefig(figures / "figure_05_susceptibility_and_events.png", dpi=220)
    plt.close(figure)

    class_colors = {
        "Low": "#2c7bb6",
        "Moderate": "#abd9e9",
        "High": "#fdae61",
        "Very High": "#d7191c",
    }
    figure, axis = plt.subplots(figsize=(10, 8))
    for label in class_labels:
        subset = gns[gns["risk_class"] == label]
        subset.plot(
            ax=axis,
            color=class_colors.get(label, "#808080"),
            edgecolor="white",
            linewidth=0.6,
            label=label,
        )
    gns.boundary.plot(ax=axis, color="#333333", linewidth=0.35)
    top = gns.nsmallest(5, "risk_rank")
    label_offsets = [(-38, 18), (18, 10), (-38, -18), (-20, 18), (15, 10)]
    for (_, row), offset in zip(top.iterrows(), label_offsets, strict=False):
        point = row.geometry.representative_point()
        axis.annotate(
            row["GND_Name"],
            (point.x, point.y),
            xytext=offset,
            textcoords="offset points",
            fontsize=7,
            ha="center",
            arrowprops={"arrowstyle": "-", "color": "#333333", "lw": 0.5},
            bbox={"boxstyle": "round,pad=0.15", "fc": "white", "alpha": 0.65, "ec": "none"},
        )
    axis.legend(title="Relative risk class")
    axis.set_title(f"{division_name} LS-LRSI by GN division")
    axis.set_xlabel("Easting (m)")
    axis.set_ylabel("Northing (m)")
    add_map_aids(axis)
    add_source_note(
        figure,
        "Source: Author's LS-LRSI calculations from verified project inputs. "
        f"Classes are relative quartiles for {len(gns)} {division_name} GNs, not warnings.",
    )
    figure.tight_layout(rect=(0, 0.025, 1, 1))
    figure.savefig(figures / "figure_06_final_gn_risk.png", dpi=220)
    plt.close(figure)

    top = gns.nsmallest(10, "risk_rank").sort_values("risk_score")
    figure, axes = plt.subplots(1, 2, figsize=(13, 7))
    axes[0].barh(top["GND_Name"], top["risk_score"], color="#c43c39")
    axes[0].set_xlabel("LS-LRSI score (0–100)")
    axes[0].set_title("Ten highest relative risk scores")
    scatter = axes[1].scatter(
        top["susceptibility_score"],
        top["exposure_score"],
        c=top["risk_score"],
        cmap="RdYlGn_r",
        s=70,
    )
    for _, row in top.iterrows():
        label_on_left = row["susceptibility_score"] > 56.5
        axes[1].annotate(
            row["GND_Name"],
            (row["susceptibility_score"], row["exposure_score"]),
            fontsize=7,
            xytext=(-3, 3) if label_on_left else (3, 3),
            textcoords="offset points",
            ha="right" if label_on_left else "left",
        )
    axes[1].set_xlabel("Susceptibility score (0–100)")
    axes[1].set_ylabel("Exposure score (0–100)")
    axes[1].set_title("Physical susceptibility and social exposure")
    colorbar = figure.colorbar(scatter, ax=axes[1], shrink=0.78)
    colorbar.set_label("Final LS-LRSI score (0–100)")
    add_source_note(
        figure,
        "Source: Author's calculations from the verified project inputs; see DATA_SOURCES.md.",
    )
    figure.tight_layout(rect=(0, 0.025, 1, 1))
    figure.savefig(figures / "figure_07_top_risk_components.png", dpi=220)
    plt.close(figure)

    stability = gns.sort_values("sensitivity_class_stability")
    figure, axis = plt.subplots(figsize=(10, 9))
    axis.barh(
        stability["GND_Name"],
        stability["sensitivity_class_stability"] * 100,
        color="#4c78a8",
    )
    axis.set_xlabel("Simulations retaining the baseline risk class (%)")
    axis.set_title(f"GN risk-class stability under {len(sensitivity_draws)} weight perturbations")
    axis.set_xlim(0, 100)
    add_source_note(
        figure,
        "Source: Author's 500-run Dirichlet perturbation analysis of the seven "
        "susceptibility weights.",
    )
    figure.tight_layout(rect=(0, 0.025, 1, 1))
    figure.savefig(figures / "figure_08_weight_sensitivity.png", dpi=220)
    plt.close(figure)

    workflow_steps = [
        "1. Acquire and verify\nsource data + SHA-256 manifest",
        f"2. Reproject, clip and align\nto {analysis_crs} at 30 m",
        "3. Derive and normalize seven\nphysical susceptibility indicators",
        "4. Weighted sum produces the\n30 m susceptibility surface",
        "5. Aggregate each GN using\n0.6 mean + 0.4 90th percentile",
        "6. Combine susceptibility (70%)\nand exposure (30%) geometrically",
        "7. Rank, classify, test weight\nsensitivity and document limits",
    ]
    figure, axis = plt.subplots(figsize=(8, 10))
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")
    y_positions = np.linspace(0.92, 0.08, len(workflow_steps))
    colors = ["#e8eef5", "#e8eef5", "#fff3cd", "#fff3cd", "#d9edf7", "#f8d7da", "#e2f0d9"]
    workflow_rows = zip(workflow_steps, y_positions, colors, strict=False)
    for index, (text, y_value, color) in enumerate(workflow_rows):
        axis.text(
            0.5,
            y_value,
            text,
            ha="center",
            va="center",
            fontsize=10.5,
            bbox={
                "boxstyle": "round,pad=0.65",
                "facecolor": color,
                "edgecolor": "#375a7f",
                "linewidth": 1.2,
            },
        )
        if index < len(workflow_steps) - 1:
            axis.annotate(
                "",
                xy=(0.5, y_positions[index + 1] + 0.045),
                xytext=(0.5, y_value - 0.045),
                arrowprops={"arrowstyle": "->", "color": "#375a7f", "lw": 1.5},
            )
    axis.set_title(f"Reusable {division_name} LS-LRSI workflow", fontsize=14, pad=16)
    add_source_note(
        figure,
        "Source: Author's workflow implemented in scripts/build_index.py and documented "
        "in METHODOLOGY.md.",
    )
    figure.tight_layout(rect=(0, 0.025, 1, 1))
    figure.savefig(
        figures / "figure_09_index_workflow.png",
        dpi=220,
        bbox_inches="tight",
    )
    plt.close(figure)
