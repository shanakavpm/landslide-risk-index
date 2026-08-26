"""Build the reproducible Haldummulla Location-Specific Landslide Risk Index.

The workflow separates physical susceptibility at 30 m from social exposure at
GN-division level. It uses a transparent weighted index because the available
open landslide inventory is too small and spatially uncertain for supervised
30 m model training.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.features import geometry_mask, rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from rasterstats import zonal_stats
from scipy import ndimage, stats

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lslrsi.config import load_project_config  # noqa: E402
from lslrsi.plotting import create_analysis_figures  # noqa: E402
from lslrsi.scoring import (  # noqa: E402 - supports direct script execution
    fill_nearest,
    fill_small_gaps,
    percentile_bounds,
    relative_class_codes,
    relative_class_labels,
    robust_scale,
    robust_series,
    validate_weights,
    weighted_geometric_risk,
    weighted_sum,
)

RAW = ROOT / "data" / "raw"
CONFIG = load_project_config(ROOT / "config" / "project.json")
BASELINE_PATH = ROOT / "config" / "normalization_baseline.json"
CRS = CONFIG["analysis_crs"]
RESOLUTION = float(CONFIG["analysis_resolution_m"])
NODATA = -9999.0


@dataclass(frozen=True)
class OutputPaths:
    """Output locations for one complete pipeline run."""

    root: Path

    @property
    def figures(self) -> Path:
        """Return the directory for generated figures."""
        return self.root / "figures"

    @property
    def tables(self) -> Path:
        """Return the directory for generated tables."""
        return self.root / "tables"

    @property
    def rasters(self) -> Path:
        """Return the directory for generated raster files."""
        return self.root / "rasters"

    @property
    def vectors(self) -> Path:
        """Return the directory for generated vector files."""
        return self.root / "vectors"

    def create(self) -> None:
        """Create all output subdirectories for a pipeline run."""
        for directory in (self.figures, self.tables, self.rasters, self.vectors):
            directory.mkdir(parents=True, exist_ok=True)


EXPECTED_OUTPUTS = {
    "figures/figure_01_study_area_population.png",
    "figures/figure_02_physical_indicators.png",
    "figures/figure_03_indicator_distributions.png",
    "figures/figure_04_indicator_correlation.png",
    "figures/figure_05_susceptibility_and_events.png",
    "figures/figure_06_final_gn_risk.png",
    "figures/figure_07_top_risk_components.png",
    "figures/figure_08_weight_sensitivity.png",
    "figures/figure_09_index_workflow.png",
    "tables/analysis_metadata.json",
    "tables/haldummulla_gn_risk_scores.csv",
    "tables/indicator_spearman_correlation.csv",
    "tables/landcover_composition.csv",
    "tables/nasa_catalogue_plausibility_check.csv",
    "tables/preprocessing_quality_audit.csv",
    "tables/raster_indicator_summary.csv",
    "tables/sensitivity_summary.csv",
    "rasters/landslide_susceptibility_0_100.tif",
    "vectors/haldummulla_gn_risk.gpkg",
    "vectors/haldummulla_inputs.gpkg",
}


def validate_staged_outputs(paths: OutputPaths) -> None:
    """Ensure a staged run is complete before it replaces published outputs."""
    missing = [
        relative
        for relative in sorted(EXPECTED_OUTPUTS)
        if not (paths.root / relative).is_file() or (paths.root / relative).stat().st_size == 0
    ]
    if missing:
        raise RuntimeError(f"Build did not produce required outputs: {missing}")


def publish_outputs(staged_root: Path, temporary_root: Path) -> None:
    """Promote a complete staged output tree, restoring the old tree on failure."""
    final_root = ROOT / "outputs"
    backup_root = temporary_root / "previous_outputs"
    if final_root.exists():
        final_root.replace(backup_root)
    try:
        staged_root.replace(final_root)
    except OSError:
        if backup_root.exists() and not final_root.exists():
            backup_root.replace(final_root)
        raise
    if backup_root.exists():
        shutil.rmtree(backup_root)


def atomic_write_json(path: Path, payload: dict) -> None:
    """Atomically replace a JSON file on the same filesystem."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def require_columns(frame: pd.DataFrame, required: set[str], source_name: str) -> None:
    """Fail with a clear message when an input schema has changed."""
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{source_name} is missing required columns: {missing}")


def load_normalization_baseline(refresh: bool) -> dict:
    """Load fixed normalisation bounds, or prepare a new baseline when requested."""
    if not refresh:
        if not BASELINE_PATH.exists():
            raise FileNotFoundError(
                f"Missing {BASELINE_PATH.name}. Restore the committed baseline or run with "
                "--refresh-normalization-baseline after an intentional methodology review."
            )
        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        if baseline.get("study_area") != CONFIG["study_area"]:
            raise ValueError("The normalisation baseline is for a different study area.")
        if baseline.get("analysis_crs") != CRS:
            raise ValueError("The normalisation baseline uses a different analysis CRS.")
        if not math.isclose(
            float(baseline.get("analysis_resolution_m", -1)),
            RESOLUTION,
            abs_tol=1e-9,
        ):
            raise ValueError("The normalisation baseline uses a different raster resolution.")
        for section in ("raster_indicators", "exposure_indicators"):
            if not isinstance(baseline.get(section), dict):
                raise ValueError(f"The normalisation baseline lacks a valid {section} section.")
        return baseline
    return {
        "schema_version": 1,
        "study_area": CONFIG["study_area"],
        "analysis_crs": CRS,
        "analysis_resolution_m": RESOLUTION,
        "method": "2nd and 98th percentile bounds from the stated baseline inputs",
        "raster_indicators": {},
        "exposure_indicators": {},
    }


def get_bounds(
    baseline: dict,
    section: str,
    name: str,
    values: np.ndarray,
    refresh: bool,
) -> dict[str, float]:
    """Read fixed scaling bounds or calculate them during a baseline refresh."""
    if refresh:
        bounds = percentile_bounds(values)
        baseline[section][name] = bounds
        return bounds
    try:
        return baseline[section][name]
    except KeyError as error:
        raise KeyError(f"Normalisation baseline lacks {section}.{name}.") from error


def target_grid(gns: gpd.GeoDataFrame):
    """Create the aligned analysis grid and study-area mask."""
    xmin, ymin, xmax, ymax = gns.total_bounds
    xmin = math.floor(xmin / RESOLUTION) * RESOLUTION
    ymin = math.floor(ymin / RESOLUTION) * RESOLUTION
    xmax = math.ceil(xmax / RESOLUTION) * RESOLUTION
    ymax = math.ceil(ymax / RESOLUTION) * RESOLUTION
    width = int(round((xmax - xmin) / RESOLUTION))
    height = int(round((ymax - ymin) / RESOLUTION))
    transform = from_origin(xmin, ymax, RESOLUTION, RESOLUTION)
    study_geometry = gns.geometry.union_all()
    mask = geometry_mask(
        [study_geometry], out_shape=(height, width), transform=transform, invert=True
    )
    return transform, width, height, mask


def reproject_sources(
    paths: list[Path],
    transform,
    width: int,
    height: int,
    resampling: Resampling,
) -> np.ndarray:
    """Merge source rasters onto the common analysis grid."""
    destination = np.full((height, width), np.nan, dtype="float32")
    for path in paths:
        with rasterio.open(path) as source:
            temporary = np.full((height, width), np.nan, dtype="float32")
            reproject(
                source=rasterio.band(source, 1),
                destination=temporary,
                src_transform=source.transform,
                src_crs=source.crs,
                src_nodata=source.nodata,
                dst_transform=transform,
                dst_crs=CRS,
                dst_nodata=np.nan,
                resampling=resampling,
            )
            valid = np.isfinite(temporary)
            destination[valid] = temporary[valid]
    return destination


def write_raster(path: Path, array: np.ndarray, transform, dtype="float32", nodata=NODATA) -> None:
    """Write a compressed, georeferenced single-band raster."""
    output = np.where(np.isfinite(array), array, nodata).astype(dtype)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=output.shape[0],
        width=output.shape[1],
        count=1,
        dtype=dtype,
        crs=CRS,
        transform=transform,
        nodata=nodata,
        compress="deflate",
        tiled=True,
    ) as dataset:
        dataset.write(output, 1)


def load_osm_lines(path: Path, allowed_highways: set[str] | None = None) -> gpd.GeoDataFrame:
    """Load OSM line features and project them into the analysis CRS."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        if allowed_highways is not None and tags.get("highway") not in allowed_highways:
            continue
        coordinates = [
            (point["lon"], point["lat"])
            for point in element.get("geometry", [])
            if "lon" in point and "lat" in point
        ]
        if len(coordinates) >= 2:
            from shapely.geometry import LineString

            features.append(
                {"osm_id": element.get("id"), **tags, "geometry": LineString(coordinates)}
            )
    return gpd.GeoDataFrame(features, crs=4326).to_crs(CRS)


def load_osm_amenities(path: Path) -> gpd.GeoDataFrame:
    """Load OSM amenity points and project them into the analysis CRS."""
    from shapely.geometry import Point

    payload = json.loads(path.read_text(encoding="utf-8"))
    features = []
    for element in payload.get("elements", []):
        lon = element.get("lon")
        lat = element.get("lat")
        if lon is None or lat is None:
            center = element.get("center", {})
            lon, lat = center.get("lon"), center.get("lat")
        if lon is None or lat is None:
            continue
        tags = element.get("tags", {})
        features.append(
            {
                "osm_type": element.get("type"),
                "osm_id": element.get("id"),
                "amenity": tags.get("amenity"),
                "name": tags.get("name"),
                "geometry": Point(lon, lat),
            }
        )
    return gpd.GeoDataFrame(features, crs=4326).to_crs(CRS)


def proximity_indicator(lines: gpd.GeoDataFrame, shape, transform, decay_m: float, mask):
    """Calculate distance and exponential proximity rasters for line features."""
    burned = rasterize(
        [(geom, 1) for geom in lines.geometry if geom is not None and not geom.is_empty],
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=True,
    )
    if not burned.any():
        raise ValueError("No line features intersect the study grid.")
    distance = ndimage.distance_transform_edt(burned == 0, sampling=RESOLUTION).astype("float32")
    indicator = np.exp(-distance / decay_m).astype("float32")
    indicator[~mask] = np.nan
    distance[~mask] = np.nan
    return distance, indicator


def parse_housing(config: dict) -> pd.DataFrame:
    """Extract and validate Haldummulla housing records from the DCS workbook."""
    housing = pd.read_excel(RAW / config["housing_file"], header=3)
    require_columns(
        housing,
        {
            "DS_Division\nName",
            "GN_Division\nCode",
            "GN_Division\nName",
            "Occupied Housing Units",
        },
        "DCS housing workbook",
    )
    housing = housing[housing["DS_Division\nName"].astype(str).eq(config["division_name"])].copy()
    housing = housing.rename(
        columns={
            "GN_Division\nCode": "gn_code_numeric",
            "GN_Division\nName": "gn_name_excel",
            "Occupied Housing Units": "occupied_housing_units",
        }
    )
    housing["gn_code_numeric"] = pd.to_numeric(housing["gn_code_numeric"], errors="coerce").astype(
        "Int64"
    )
    if housing.empty or housing["gn_code_numeric"].isna().any():
        raise ValueError("DCS housing data has no usable GN records for the selected division.")
    if housing["gn_code_numeric"].duplicated().any():
        raise ValueError("DCS housing data contains duplicate GN codes.")
    return housing[["gn_code_numeric", "gn_name_excel", "occupied_housing_units"]]


def nasa_candidates(gns: gpd.GeoDataFrame, search_terms: list[str]) -> gpd.GeoDataFrame:
    """Find catalogue records that may relate to the study area."""
    from shapely.geometry import Point

    catalog = pd.read_csv(RAW / "nasa_global_landslide_catalog.csv", low_memory=False)
    require_columns(
        catalog,
        {
            "country_name",
            "event_id",
            "event_date",
            "event_title",
            "location_description",
            "location_accuracy",
            "longitude",
            "latitude",
        },
        "NASA landslide catalogue",
    )
    sri = catalog[catalog["country_name"].astype(str).str.casefold().eq("sri lanka")].copy()
    text = (
        sri["event_title"].fillna("").astype(str)
        + " "
        + sri["location_description"].fillna("").astype(str)
    ).str.casefold()
    pattern = "|".join(re.escape(term.casefold()) for term in search_terms)
    candidates = sri[text.str.contains(pattern, regex=True)].copy()
    candidates = candidates.dropna(subset=["longitude", "latitude"])
    candidates["geometry"] = [
        Point(xy) for xy in zip(candidates["longitude"], candidates["latitude"], strict=False)
    ]
    result = gpd.GeoDataFrame(candidates, crs=4326).to_crs(CRS)
    result["inside_study_area"] = result.geometry.within(gns.geometry.union_all())
    return result


def build_index(
    paths: OutputPaths,
    refresh_baseline: bool,
    baseline: dict,
) -> dict:
    """Run the complete index workflow into a staging output tree."""
    paths.create()
    FIGURES = paths.figures
    TABLES = paths.tables
    RASTERS = paths.rasters
    VECTORS = paths.vectors
    gns = gpd.read_file(RAW / CONFIG["boundary_file"])
    if gns.crs is None:
        raise ValueError("DCS GN boundaries do not declare a coordinate reference system.")
    require_columns(
        gns,
        {
            "GND_Code",
            "GND_Name",
            "Population",
            "Male",
            "Female",
            "Age_0_14",
            "Age_65_and",
        },
        "DCS GN boundaries",
    )
    gns = gns.to_crs(CRS)
    gns["geometry"] = gns.geometry.make_valid()
    if gns.empty or gns.geometry.is_empty.any() or gns.geometry.isna().any():
        raise ValueError("DCS GN boundaries contain missing or empty geometries.")
    numeric_columns = ["Population", "Male", "Female", "Age_0_14", "Age_65_and"]
    for column in numeric_columns:
        gns[column] = pd.to_numeric(gns[column], errors="coerce")
    if gns[numeric_columns].isna().any().any():
        raise ValueError("DCS GN boundaries contain missing or non-numeric population fields.")
    if (gns["Population"] <= 0).any():
        raise ValueError("Every GN division must have a positive population.")
    gns["gn_code_numeric"] = pd.to_numeric(gns["GND_Code"], errors="coerce").astype("Int64")
    if gns["gn_code_numeric"].isna().any() or gns["gn_code_numeric"].duplicated().any():
        raise ValueError("DCS GN boundaries require unique numeric GN codes.")
    housing = parse_housing(CONFIG)
    gns = gns.merge(housing, on="gn_code_numeric", how="left", validate="one_to_one")
    if gns["occupied_housing_units"].isna().any():
        missing = gns.loc[gns["occupied_housing_units"].isna(), "GND_Name"].tolist()
        raise ValueError(f"Housing data did not join for: {missing}")
    gns["area_km2"] = gns.geometry.area / 1_000_000
    if (gns["area_km2"] <= 0).any():
        raise ValueError("Every GN division must have a positive polygon area.")
    gns["population_density_km2"] = gns["Population"] / gns["area_km2"]
    gns["housing_density_km2"] = gns["occupied_housing_units"] / gns["area_km2"]
    gns["vulnerable_population_share"] = (gns["Age_0_14"] + gns["Age_65_and"]) / gns["Population"]

    transform, width, height, study_mask = target_grid(gns)
    shape = (height, width)
    print(f"Target grid: {width} x {height} cells at {RESOLUTION:.0f} m")

    dem = reproject_sources(
        [RAW / "copdem_n06e080.tif", RAW / "copdem_n06e081.tif"],
        transform,
        width,
        height,
        Resampling.bilinear,
    )
    dem_valid = study_mask & np.isfinite(dem)
    dem_missing_before_fill = int((study_mask & ~np.isfinite(dem)).sum())
    if dem_valid.sum() / study_mask.sum() < 0.995:
        raise ValueError("DEM coverage is incomplete within the study area.")
    dem_filled = fill_nearest(dem, dem_valid)
    dz_dy, dz_dx = np.gradient(dem_filled, RESOLUTION, RESOLUTION)
    slope = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy))).astype("float32")
    relief_window = int(round(1000 / RESOLUTION))
    if relief_window % 2 == 0:
        relief_window += 1
    local_relief = (
        ndimage.maximum_filter(dem_filled, size=relief_window)
        - ndimage.minimum_filter(dem_filled, size=relief_window)
    ).astype("float32")
    for array in (dem, slope, local_relief):
        array[~study_mask] = np.nan

    rainfall = reproject_sources(
        [RAW / "chirps_1981_2024_mean_annual.tif"],
        transform,
        width,
        height,
        Resampling.bilinear,
    )
    # The global CHIRPS GeoTIFF contains -9999 cells but does not declare a
    # nodata value. Treat negative precipitation as missing before QA/filling.
    rainfall[rainfall < 0] = np.nan
    rainfall_missing_before_fill = int((study_mask & ~np.isfinite(rainfall)).sum())
    rainfall = fill_small_gaps("rainfall", rainfall, study_mask)
    rainfall[~study_mask] = np.nan
    landcover = reproject_sources(
        [RAW / "worldcover_2021_n06e078.tif", RAW / "worldcover_2021_n06e081.tif"],
        transform,
        width,
        height,
        Resampling.nearest,
    )
    landcover_missing_before_fill = int((study_mask & ~np.isfinite(landcover)).sum())
    landcover = fill_small_gaps("land cover", landcover, study_mask)
    landcover[~study_mask] = np.nan
    clay_raw = reproject_sources(
        [RAW / "soilgrids_clay_0_5cm_mean_250m.tif"],
        transform,
        width,
        height,
        Resampling.bilinear,
    )
    clay_percent = clay_raw / 10.0  # SoilGrids clay unit is g/kg (conversion to mass %).
    clay_missing_before_fill = int((study_mask & ~np.isfinite(clay_percent)).sum())
    clay_percent = fill_small_gaps("topsoil clay", clay_percent, study_mask)
    clay_percent[~study_mask] = np.nan

    highway_classes = {
        "motorway",
        "trunk",
        "primary",
        "secondary",
        "tertiary",
        "unclassified",
        "residential",
        "service",
        "living_street",
        "track",
    }
    roads = load_osm_lines(RAW / "osm_roads.json", highway_classes)
    streams = load_osm_lines(RAW / "osm_waterways.json")
    amenities = load_osm_amenities(RAW / "osm_critical_amenities.json")
    study_polygon = gpd.GeoDataFrame(geometry=[gns.geometry.union_all()], crs=CRS)
    roads = gpd.clip(roads, study_polygon)
    streams = gpd.clip(streams, study_polygon)
    amenities = gpd.clip(amenities, study_polygon)
    road_distance, road_proximity = proximity_indicator(
        roads, shape, transform, CONFIG["distance_decay_m"]["road"], study_mask
    )
    stream_distance, stream_proximity = proximity_indicator(
        streams, shape, transform, CONFIG["distance_decay_m"]["stream"], study_mask
    )

    landcover_lookup = {
        int(key): float(value) for key, value in CONFIG["landcover_risk_scores"].items()
    }
    landcover_risk = np.full(shape, np.nan, dtype="float32")
    for code, value in landcover_lookup.items():
        landcover_risk[landcover == code] = value
    if np.isnan(landcover_risk[study_mask]).any():
        missing_codes = np.unique(landcover[study_mask & np.isnan(landcover_risk)])
        raise ValueError(f"Unmapped WorldCover classes: {missing_codes}")

    raster_indicator_inputs = {
        "slope": slope,
        "rainfall": rainfall,
        "local_relief": local_relief,
        "clay": clay_percent,
    }
    raster_bounds = {
        name: get_bounds(
            baseline,
            "raster_indicators",
            name,
            array[study_mask & np.isfinite(array)],
            refresh_baseline,
        )
        for name, array in raster_indicator_inputs.items()
    }
    study_cell_count = int(study_mask.sum())
    preprocessing_records = []
    layer_audit_inputs = [
        (
            "Copernicus DEM GLO-30",
            "elevation_m",
            dem,
            dem_missing_before_fill,
            "approximately 30 m",
            "bilinear",
            None,
            "DSM used to derive slope and local relief",
        ),
        (
            "CHIRPS v2.0 1981-2024 mean annual rainfall",
            "rainfall",
            rainfall,
            rainfall_missing_before_fill,
            "0.05 degrees (approximately 5 km)",
            "bilinear",
            raster_bounds["rainfall"],
            "Resampling does not create 30 m rainfall observations",
        ),
        (
            "ESA WorldCover 2021 v200",
            "landcover",
            landcover,
            landcover_missing_before_fill,
            "10 m",
            "nearest neighbour",
            None,
            "Categorical classes retained before lookup scoring",
        ),
        (
            "SoilGrids 2.0 clay 0-5 cm",
            "clay",
            clay_percent,
            clay_missing_before_fill,
            "250 m",
            "bilinear",
            raster_bounds["clay"],
            "Surface-clay proxy; not a geotechnical strength layer",
        ),
        (
            "Derived from Copernicus DEM GLO-30",
            "slope",
            slope,
            0,
            "30 m target grid",
            "terrain derivative",
            raster_bounds["slope"],
            "Slope in degrees",
        ),
        (
            "Derived from Copernicus DEM GLO-30",
            "local_relief",
            local_relief,
            0,
            "approximately 1 km moving window",
            "maximum minus minimum",
            raster_bounds["local_relief"],
            "Overlaps partly with slope; therefore receives a smaller weight",
        ),
    ]
    for (
        source_name,
        layer_name,
        array,
        missing_count,
        native_detail,
        method,
        bounds,
        note,
    ) in layer_audit_inputs:
        valid_values = array[study_mask & np.isfinite(array)]
        below_count = 0
        above_count = 0
        p02 = np.nan
        p98 = np.nan
        if bounds is not None:
            p02 = float(bounds["p02"])
            p98 = float(bounds["p98"])
            below_count = int((valid_values < p02).sum())
            above_count = int((valid_values > p98).sum())
        preprocessing_records.append(
            {
                "source_or_derivation": source_name,
                "analysis_layer": layer_name,
                "native_detail": native_detail,
                "processing_method": method,
                "target_resolution_m": RESOLUTION,
                "study_cells": study_cell_count,
                "missing_cells_before_fill": missing_count,
                "missing_percent_before_fill": 100 * missing_count / study_cell_count,
                "filled_cells": missing_count,
                "valid_cells_after_fill": int(valid_values.size),
                "baseline_p02": p02,
                "baseline_p98": p98,
                "cells_below_p02": below_count,
                "cells_above_p98": above_count,
                "clipped_percent": 100 * (below_count + above_count) / valid_values.size,
                "quality_note": note,
            }
        )
    pd.DataFrame(preprocessing_records).to_csv(
        TABLES / "preprocessing_quality_audit.csv", index=False
    )
    indicators = {
        "slope": robust_scale(slope, study_mask, raster_bounds["slope"]),
        "rainfall": robust_scale(rainfall, study_mask, raster_bounds["rainfall"]),
        "landcover": landcover_risk,
        "local_relief": robust_scale(local_relief, study_mask, raster_bounds["local_relief"]),
        "clay": robust_scale(clay_percent, study_mask, raster_bounds["clay"]),
        "road_proximity": road_proximity,
        "stream_proximity": stream_proximity,
    }
    weights = CONFIG["susceptibility_weights"]
    validate_weights(weights, set(indicators), "Susceptibility")
    susceptibility = weighted_sum(indicators, weights)
    susceptibility[~study_mask] = np.nan

    raw_rasters = {
        "elevation_m": dem,
        "slope_degrees": slope,
        "local_relief_1km_m": local_relief,
        "mean_annual_rainfall_mm": rainfall,
        "worldcover_class": landcover,
        "clay_percent": clay_percent,
        "distance_to_road_m": road_distance,
        "distance_to_stream_m": stream_distance,
    }
    for name, array in raw_rasters.items():
        write_raster(RASTERS / f"{name}.tif", array, transform)
    for name, array in indicators.items():
        write_raster(RASTERS / f"indicator_{name}_0_1.tif", array, transform)
    susceptibility_path = RASTERS / "landslide_susceptibility_0_100.tif"
    write_raster(susceptibility_path, susceptibility, transform)

    # GN-level zonal summaries for every physical indicator and susceptibility.
    zonal_layers = {**indicators, "susceptibility": susceptibility}
    for name, array in zonal_layers.items():
        summaries = zonal_stats(
            gns.geometry,
            array,
            affine=transform,
            stats=["mean", "percentile_90"],
            nodata=np.nan,
        )
        gns[f"{name}_mean"] = [item.get("mean") for item in summaries]
        gns[f"{name}_p90"] = [item.get("percentile_90") for item in summaries]
    gns["susceptibility_score"] = 0.6 * gns["susceptibility_mean"] + 0.4 * gns["susceptibility_p90"]

    amenity_join = gpd.sjoin(
        amenities[["amenity", "geometry"]],
        gns[["GND_Name", "geometry"]],
        predicate="within",
        how="left",
    )
    amenity_counts = amenity_join.groupby("index_right").size()
    gns["critical_amenity_count"] = gns.index.map(amenity_counts).fillna(0).astype(int)
    gns["critical_infrastructure_density_km2"] = gns["critical_amenity_count"] / gns["area_km2"]

    exposure_inputs = {
        "population_density": "population_density_km2",
        "housing_density": "housing_density_km2",
        "vulnerable_population_share": "vulnerable_population_share",
        "critical_infrastructure_density": "critical_infrastructure_density_km2",
    }
    exposure_bounds = {
        short_name: get_bounds(
            baseline,
            "exposure_indicators",
            short_name,
            pd.to_numeric(gns[column], errors="coerce").dropna().to_numpy(float),
            refresh_baseline,
        )
        for short_name, column in exposure_inputs.items()
    }
    for short_name, column in exposure_inputs.items():
        gns[f"{short_name}_normalized"] = robust_series(gns[column], exposure_bounds[short_name])
    exposure_weights = CONFIG["exposure_weights"]
    validate_weights(exposure_weights, set(exposure_inputs), "Exposure")
    normalized_exposure = {
        name: gns[f"{name}_normalized"].to_numpy(float) for name in exposure_inputs
    }
    gns["exposure_score"] = weighted_sum(normalized_exposure, exposure_weights)

    risk_weights = CONFIG["risk_component_weights"]
    epsilon = 1e-6
    gns["risk_score"] = weighted_geometric_risk(
        gns["susceptibility_score"],
        gns["exposure_score"],
        risk_weights,
        epsilon,
    )
    class_labels = CONFIG["risk_class_labels"]
    gns["risk_class"] = relative_class_labels(gns["risk_score"], class_labels).to_numpy()
    gns["risk_rank"] = gns["risk_score"].rank(method="min", ascending=False).astype(int)

    # Rasterise the GN exposure score so the susceptibility/exposure distinction is visible.
    exposure_raster = rasterize(
        [(geom, score) for geom, score in zip(gns.geometry, gns["exposure_score"], strict=False)],
        out_shape=shape,
        transform=transform,
        fill=np.nan,
        dtype="float32",
    )
    write_raster(RASTERS / "gn_exposure_score_0_100.tif", exposure_raster, transform)

    candidates = nasa_candidates(gns, CONFIG["nasa_search_terms"])
    validation_records = []
    valid_susceptibility = susceptibility[study_mask & np.isfinite(susceptibility)]
    inverse_transformer = Transformer.from_crs(CRS, 4326, always_xy=True)
    for _, event in candidates.iterrows():
        row, col = rasterio.transform.rowcol(transform, event.geometry.x, event.geometry.y)
        score = np.nan
        percentile = np.nan
        if 0 <= row < height and 0 <= col < width and study_mask[row, col]:
            score = float(susceptibility[row, col])
            percentile = float(stats.percentileofscore(valid_susceptibility, score))
        lon, lat = inverse_transformer.transform(event.geometry.x, event.geometry.y)
        validation_records.append(
            {
                "event_id": event["event_id"],
                "event_date": event["event_date"],
                "event_title": event["event_title"],
                "location_description": event["location_description"],
                "location_accuracy": event["location_accuracy"],
                "longitude": lon,
                "latitude": lat,
                "inside_study_area": bool(event["inside_study_area"]),
                "susceptibility_score_at_catalogue_point": score,
                "study_area_percentile": percentile,
            }
        )
    plausibility = pd.DataFrame(validation_records)
    plausibility.to_csv(TABLES / "nasa_catalogue_plausibility_check.csv", index=False)

    # Weight sensitivity: draw plausible weights around the stated base weights.
    factor_names = list(weights)
    factor_matrix = np.column_stack(
        [
            0.6 * gns[f"{name}_mean"].to_numpy(float) + 0.4 * gns[f"{name}_p90"].to_numpy(float)
            for name in factor_names
        ]
    )
    base_weights = np.array([weights[name] for name in factor_names], dtype=float)
    base_factor_composite = np.maximum(factor_matrix @ base_weights, epsilon)
    sensitivity_config = CONFIG["sensitivity"]
    rng = np.random.default_rng(int(sensitivity_config["random_seed"]))
    draws = rng.dirichlet(
        base_weights * float(sensitivity_config["dirichlet_concentration"]),
        size=int(sensitivity_config["iterations"]),
    )
    baseline_rank = stats.rankdata(-gns["risk_score"].to_numpy(float))
    baseline_class = relative_class_codes(gns["risk_score"].to_numpy())
    correlations = []
    class_matches = np.zeros((len(draws), len(gns)), dtype=bool)
    simulated_scores = np.zeros((len(draws), len(gns)), dtype=float)
    exposure_fraction = np.maximum(gns["exposure_score"].to_numpy(float) / 100, epsilon)
    for index, draw in enumerate(draws):
        # Apply the relative change from each weight draw to the exact baseline
        # GN susceptibility score. This keeps the simulation centred on the
        # reported score while using factor-specific GN summaries for changes.
        simulated_susceptibility = gns["susceptibility_score"].to_numpy(float) * (
            (factor_matrix @ draw) / base_factor_composite
        )
        simulated_risk = weighted_geometric_risk(
            simulated_susceptibility,
            exposure_fraction * 100,
            risk_weights,
            epsilon,
        )
        simulated_scores[index] = simulated_risk
        correlations.append(
            stats.spearmanr(baseline_rank, stats.rankdata(-simulated_risk)).statistic
        )
        simulated_class = relative_class_codes(simulated_risk)
        class_matches[index] = simulated_class == baseline_class
    gns["sensitivity_class_stability"] = class_matches.mean(axis=0)
    gns["sensitivity_score_p05"] = np.quantile(simulated_scores, 0.05, axis=0)
    gns["sensitivity_score_p95"] = np.quantile(simulated_scores, 0.95, axis=0)
    sensitivity_summary = pd.DataFrame(
        {
            "metric": ["spearman_rank_correlation"],
            "p05": [np.quantile(correlations, 0.05)],
            "median": [np.median(correlations)],
            "p95": [np.quantile(correlations, 0.95)],
            "iterations": [len(draws)],
        }
    )
    sensitivity_summary.to_csv(TABLES / "sensitivity_summary.csv", index=False)

    selected_columns = [
        "GND_Code",
        "GND_Name",
        "Population",
        "occupied_housing_units",
        "area_km2",
        "population_density_km2",
        "housing_density_km2",
        "vulnerable_population_share",
        "critical_amenity_count",
        "critical_infrastructure_density_km2",
        "susceptibility_mean",
        "susceptibility_p90",
        "susceptibility_score",
        "exposure_score",
        "risk_score",
        "risk_class",
        "risk_rank",
        "sensitivity_class_stability",
        "sensitivity_score_p05",
        "sensitivity_score_p95",
    ]
    gns[selected_columns].sort_values("risk_rank").to_csv(
        TABLES / "haldummulla_gn_risk_scores.csv", index=False
    )
    factor_summary = []
    units = {
        "elevation_m": "m",
        "slope_degrees": "degrees",
        "local_relief_1km_m": "m",
        "mean_annual_rainfall_mm": "mm/year",
        "clay_percent": "%",
        "distance_to_road_m": "m",
        "distance_to_stream_m": "m",
        "landslide_susceptibility": "index points (0-100)",
    }
    for name, array in {**raw_rasters, "landslide_susceptibility": susceptibility}.items():
        values = array[study_mask & np.isfinite(array)]
        if name == "worldcover_class":
            continue
        factor_summary.append(
            {
                "indicator": name,
                "unit": units[name],
                "valid_cells": int(values.size),
                "minimum": float(values.min()),
                "p02": float(np.quantile(values, 0.02)),
                "mean": float(values.mean()),
                "median": float(np.median(values)),
                "p98": float(np.quantile(values, 0.98)),
                "maximum": float(values.max()),
            }
        )
    pd.DataFrame(factor_summary).to_csv(TABLES / "raster_indicator_summary.csv", index=False)
    landcover_values, landcover_counts = np.unique(
        landcover[study_mask & np.isfinite(landcover)].astype(int), return_counts=True
    )
    pd.DataFrame(
        {
            "worldcover_code": landcover_values,
            "cell_count": landcover_counts,
            "area_km2": landcover_counts * RESOLUTION * RESOLUTION / 1_000_000,
            "share_percent": landcover_counts / landcover_counts.sum() * 100,
            "assigned_risk": [landcover_lookup[value] for value in landcover_values],
        }
    ).to_csv(TABLES / "landcover_composition.csv", index=False)

    output_columns = selected_columns + [f"{name}_mean" for name in factor_names] + ["geometry"]
    gns[output_columns].to_file(
        VECTORS / "haldummulla_gn_risk.gpkg", layer="gn_risk", driver="GPKG"
    )
    roads.to_file(VECTORS / "haldummulla_inputs.gpkg", layer="roads", driver="GPKG")
    streams.to_file(VECTORS / "haldummulla_inputs.gpkg", layer="waterways", driver="GPKG")
    amenities.to_file(
        VECTORS / "haldummulla_inputs.gpkg", layer="critical_amenities", driver="GPKG"
    )
    if not candidates.empty:
        candidates.to_file(
            VECTORS / "haldummulla_inputs.gpkg", layer="nasa_candidates", driver="GPKG"
        )

    create_analysis_figures(
        figures=FIGURES,
        tables=TABLES,
        gns=gns,
        transform=transform,
        slope=slope,
        rainfall=rainfall,
        local_relief=local_relief,
        landcover_risk=landcover_risk,
        clay_percent=clay_percent,
        indicators=indicators,
        raster_bounds=raster_bounds,
        susceptibility=susceptibility,
        candidates=candidates,
        class_labels=class_labels,
        random_generator=rng,
        sensitivity_draws=draws,
        division_name=CONFIG["division_name"],
        analysis_crs=CRS,
    )

    metadata = {
        "study_area": CONFIG["study_area"],
        "analysis_crs": CRS,
        "raster_resolution_m": RESOLUTION,
        "gn_divisions": int(len(gns)),
        "study_area_km2": float(gns["area_km2"].sum()),
        "population_2024_provisional": int(gns["Population"].sum()),
        "occupied_housing_units_2024_provisional": int(gns["occupied_housing_units"].sum()),
        "roads_in_study_area": int(len(roads)),
        "waterways_in_study_area": int(len(streams)),
        "critical_amenities_in_study_area": int(len(amenities)),
        "nasa_keyword_candidates": int(len(candidates)),
        "nasa_candidates_inside_study_area": int(candidates["inside_study_area"].sum())
        if len(candidates)
        else 0,
        "susceptibility_weights": weights,
        "weighting_notes": CONFIG["weighting_notes"],
        "exposure_weights": exposure_weights,
        "risk_weights": risk_weights,
        "normalization_baseline_path": str(BASELINE_PATH.relative_to(ROOT)),
        "normalization_baseline_refreshed": refresh_baseline,
        "top_five_gn_divisions": gns.nsmallest(5, "risk_rank")[
            ["GND_Name", "risk_score", "susceptibility_score", "exposure_score"]
        ].to_dict(orient="records"),
        "sensitivity_rank_correlation": sensitivity_summary.iloc[0].to_dict(),
    }
    atomic_write_json(TABLES / "analysis_metadata.json", metadata)
    return metadata


def main() -> None:
    """Parse command-line options and publish a complete index build."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh-normalization-baseline",
        action="store_true",
        help=(
            "Recalculate config/normalization_baseline.json after a deliberate "
            "methodology or study-area review."
        ),
    )
    args = parser.parse_args()
    refresh_baseline = args.refresh_normalization_baseline
    baseline = load_normalization_baseline(refresh_baseline)

    with tempfile.TemporaryDirectory(prefix=".lslrsi-", dir=ROOT) as temporary:
        temporary_root = Path(temporary)
        paths = OutputPaths(temporary_root / "outputs")
        metadata = build_index(paths, refresh_baseline, baseline)
        validate_staged_outputs(paths)
        publish_outputs(paths.root, temporary_root)

    if refresh_baseline:
        atomic_write_json(BASELINE_PATH, baseline)
        print(f"[done] refreshed fixed normalisation baseline: {BASELINE_PATH}")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
