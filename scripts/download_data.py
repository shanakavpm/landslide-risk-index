"""Download and provenance-check the input data for the Haldummulla LS-LRSI.

Only authoritative or clearly licensed endpoints are used. The script writes a
SHA-256 manifest so that the exact local inputs can be identified later.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lslrsi.config import load_project_config  # noqa: E402

RAW = ROOT / "data" / "raw"
CONFIG_PATH = ROOT / "config" / "project.json"
CHECKSUMS_PATH = ROOT / "config" / "input_checksums.json"
USER_AGENT = "Haldummulla-LSLRSI-academic-project/1.0"
SOURCE_BY_FILE = {
    "dcs_haldummulla_gn_population_2024.geojson": "DCS CPH 2024 ArcGIS FeatureServer",
    "dcs_gn_population_2024.xlsx": "Department of Census and Statistics Sri Lanka",
    "dcs_gn_housing_2024.xlsx": "Department of Census and Statistics Sri Lanka",
    "copdem_n06e080.tif": "Copernicus DEM GLO-30",
    "copdem_n06e081.tif": "Copernicus DEM GLO-30",
    "chirps_1981_2024_mean_annual.tif": "CHIRPS v2.0",
    "worldcover_2021_n06e078.tif": "ESA WorldCover 2021 v200",
    "worldcover_2021_n06e081.tif": "ESA WorldCover 2021 v200",
    "soilgrids_clay_0_5cm_mean_250m.tif": "SoilGrids 2.0",
    "nasa_global_landslide_catalog.csv": "NASA Global Landslide Catalog legacy export",
    "osm_roads.json": "OpenStreetMap via Overpass API",
    "osm_waterways.json": "OpenStreetMap via Overpass API",
    "osm_critical_amenities.json": "OpenStreetMap via Overpass API",
}


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    """Write text to a temporary file and atomically replace the destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def request_with_retry(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    stream: bool = False,
    timeout: int = 240,
    attempts: int = 4,
) -> requests.Response:
    """Send an HTTP request with exponential-backoff retries."""
    headers = {"User-Agent": USER_AGENT}
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.request(
                method,
                url,
                params=params,
                data=data,
                headers=headers,
                stream=stream,
                timeout=timeout,
            )
            response.raise_for_status()
            return response
        except (requests.RequestException, OSError) as error:
            last_error = error
            if attempt == attempts:
                break
            time.sleep(2**attempt)
    raise RuntimeError(f"Request failed after {attempts} attempts: {url}") from last_error


def download_file(
    url: str,
    destination: Path,
    minimum_bytes: int = 1000,
    force: bool = False,
) -> None:
    """Download a file atomically unless a usable local copy exists."""
    if not force and destination.exists() and destination.stat().st_size >= minimum_bytes:
        print(f"[skip] {destination.name} ({destination.stat().st_size:,} bytes)")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    with (
        request_with_retry("GET", url, stream=True) as response,
        temporary.open("wb") as handle,
    ):
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                handle.write(chunk)
    if temporary.stat().st_size < minimum_bytes:
        raise RuntimeError(f"Downloaded file is unexpectedly small: {destination}")
    temporary.replace(destination)
    print(f"[done] {destination.name} ({destination.stat().st_size:,} bytes)")


def save_json_response(
    url: str,
    destination: Path,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    method: str = "GET",
    force: bool = False,
) -> None:
    """Download a JSON response and save it atomically."""
    if not force and destination.exists() and destination.stat().st_size > 500:
        print(f"[skip] {destination.name}")
        return
    with request_with_retry(method, url, params=params, data=data) as response:
        payload = response.json()
    atomic_write_text(destination, json.dumps(payload, ensure_ascii=False))
    print(f"[done] {destination.name}")


def download_dcs_boundaries(config: dict[str, Any], force: bool = False) -> Path:
    """Download and validate the configured DCS GN boundaries."""
    destination = RAW / config["boundary_file"]
    params = {
        "where": config["study_area_query"],
        "outFields": "*",
        "outSR": "4326",
        "returnGeometry": "true",
        "f": "geojson",
    }
    save_json_response(
        config["data_urls"]["dcs_gn_population_feature_service"],
        destination,
        params=params,
        force=force,
    )
    gns = gpd.read_file(destination)
    if len(gns) < 10:
        raise RuntimeError(f"The DCS service returned only {len(gns)} GN features.")
    if not gns.geometry.is_valid.all():
        print(
            "[warn] DCS GN boundaries include invalid geometries; the build step will repair them."
        )
    print(f"[check] DCS GN features: {len(gns)}; CRS: {gns.crs}")
    return destination


def study_bbox(boundary_path: Path, pad_degrees: float = 0.02) -> tuple[float, float, float, float]:
    """Return a padded WGS 84 bounding box around the study area."""
    gns = gpd.read_file(boundary_path).to_crs(4326)
    west, south, east, north = gns.total_bounds
    return (
        float(west - pad_degrees),
        float(south - pad_degrees),
        float(east + pad_degrees),
        float(north + pad_degrees),
    )


def download_soilgrids(
    config: dict[str, Any],
    bbox: tuple[float, float, float, float],
    force: bool = False,
) -> None:
    """Download the SoilGrids clay raster for the study extent."""
    west, south, east, north = bbox
    mean_lat = (south + north) / 2
    width_m = (east - west) * 111_320 * math.cos(math.radians(mean_lat))
    height_m = (north - south) * 110_540
    width = max(50, math.ceil(width_m / 250))
    height = max(50, math.ceil(height_m / 250))
    params = {
        "SERVICE": "WCS",
        "VERSION": "1.0.0",
        "REQUEST": "GetCoverage",
        "COVERAGE": "clay_0-5cm_mean",
        "CRS": "EPSG:4326",
        "BBOX": f"{west},{south},{east},{north}",
        "WIDTH": str(width),
        "HEIGHT": str(height),
        "FORMAT": "GEOTIFF_INT16",
    }
    destination = RAW / "soilgrids_clay_0_5cm_mean_250m.tif"
    if not force and destination.exists() and destination.stat().st_size > 1000:
        print(f"[skip] {destination.name}")
        return
    temporary = destination.with_suffix(destination.suffix + ".part")
    with (
        request_with_retry(
            "GET",
            config["data_urls"]["soilgrids_wcs"],
            params=params,
            stream=True,
        ) as response,
        temporary.open("wb") as handle,
    ):
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                handle.write(chunk)
    if temporary.stat().st_size <= 1000:
        raise RuntimeError("Downloaded SoilGrids raster is unexpectedly small.")
    temporary.replace(destination)
    print(f"[done] {destination.name} ({destination.stat().st_size:,} bytes)")


def download_overpass_layer(
    destination: Path,
    query_body: str,
    endpoints: list[str],
    force: bool = False,
) -> None:
    """Download one OSM layer using the first available Overpass endpoint."""
    if not force and destination.exists() and destination.stat().st_size > 500:
        print(f"[skip] {destination.name}")
        return
    last_error: Exception | None = None
    for endpoint in endpoints:
        try:
            with request_with_retry(
                "POST",
                endpoint,
                data={"data": query_body},
                timeout=360,
                attempts=2,
            ) as response:
                payload = response.json()
            if "elements" not in payload:
                raise RuntimeError("Overpass response has no elements array")
            atomic_write_text(destination, json.dumps(payload))
            print(f"[done] {destination.name}: {len(payload['elements']):,} elements")
            return
        except (OSError, RuntimeError, requests.RequestException, ValueError) as error:
            last_error = error
            print(f"[warn] Overpass endpoint failed: {endpoint}: {error}", file=sys.stderr)
    raise RuntimeError(f"All Overpass endpoints failed for {destination.name}") from last_error


def download_osm(bbox: tuple[float, float, float, float], force: bool = False) -> None:
    """Download roads, waterways, and critical amenities from OSM."""
    west, south, east, north = bbox
    overpass_bbox = f"{south},{west},{north},{east}"
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
    ]
    road_query = f'[out:json][timeout:240];way["highway"]({overpass_bbox});out tags geom;'
    water_query = f'[out:json][timeout:240];way["waterway"]({overpass_bbox});out tags geom;'
    amenity_query = (
        "[out:json][timeout:120];("
        f'node["amenity"~"^(school|college|hospital|clinic|police|fire_station)$"]({overpass_bbox});'
        f'way["amenity"~"^(school|college|hospital|clinic|police|fire_station)$"]({overpass_bbox});'
        ");out center tags;"
    )
    download_overpass_layer(RAW / "osm_roads.json", road_query, endpoints, force)
    download_overpass_layer(RAW / "osm_waterways.json", water_query, endpoints, force)
    download_overpass_layer(RAW / "osm_critical_amenities.json", amenity_query, endpoints, force)


def build_manifest() -> None:
    """Write a provenance and checksum manifest for local input files."""
    generated_utc = datetime.now(UTC).isoformat()
    records = []
    for path in sorted(RAW.iterdir()):
        if not path.is_file() or path.name == "download_manifest.json":
            continue
        records.append(
            {
                "file": path.name,
                "source": SOURCE_BY_FILE.get(path.name, "Derived pipeline input"),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    manifest = {
        "schema_version": 1,
        "generated_utc": generated_utc,
        "files": records,
    }
    atomic_write_text(
        RAW / "download_manifest.json",
        json.dumps(manifest, indent=2),
    )
    print(f"[done] download_manifest.json ({len(records)} records)")


def verify_input_checksums(accept_updates: bool) -> None:
    """Compare source inputs with the committed baseline checksum register."""
    actual = {}
    missing = []
    for filename in SOURCE_BY_FILE:
        path = RAW / filename
        if not path.is_file():
            missing.append(filename)
        else:
            actual[filename] = sha256(path)
    if missing:
        raise FileNotFoundError(f"Required source files are missing: {sorted(missing)}")

    if accept_updates:
        payload = {"schema_version": 1, "files": actual}
        atomic_write_text(CHECKSUMS_PATH, json.dumps(payload, indent=2))
        print(f"[done] accepted source checksums: {CHECKSUMS_PATH}")
        return

    if not CHECKSUMS_PATH.is_file():
        raise FileNotFoundError(
            f"Missing {CHECKSUMS_PATH}. Run with --accept-source-updates after review."
        )
    expected = json.loads(CHECKSUMS_PATH.read_text(encoding="utf-8")).get("files", {})
    changed = sorted(
        filename for filename, digest in actual.items() if expected.get(filename) != digest
    )
    if changed:
        raise RuntimeError(
            "Source checksums differ from the committed baseline: "
            f"{changed}. Review the changes, then rerun with --accept-source-updates."
        )
    print(f"[check] verified {len(actual)} source file checksums")


def main() -> None:
    """Parse command-line options and prepare the reproducible input set."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-osm", action="store_true", help="Skip the three Overpass API requests."
    )
    parser.add_argument(
        "--refresh-downloads",
        action="store_true",
        help="Redownload source files. Must be paired with --accept-source-updates.",
    )
    parser.add_argument(
        "--accept-source-updates",
        action="store_true",
        help="Replace the committed checksum baseline after reviewing source changes.",
    )
    args = parser.parse_args()
    if args.refresh_downloads and not args.accept_source_updates:
        parser.error("--refresh-downloads requires --accept-source-updates")
    RAW.mkdir(parents=True, exist_ok=True)
    config = load_project_config(CONFIG_PATH)

    boundary_path = download_dcs_boundaries(config, args.refresh_downloads)
    bbox = study_bbox(boundary_path)
    atomic_write_text(
        RAW / "study_bbox.json",
        json.dumps(
            {"west": bbox[0], "south": bbox[1], "east": bbox[2], "north": bbox[3]},
            indent=2,
        ),
    )
    urls = config["data_urls"]
    downloads = [
        (urls["dcs_gn_population_excel"], RAW / "dcs_gn_population_2024.xlsx", 10_000),
        (urls["dcs_gn_housing_excel"], RAW / "dcs_gn_housing_2024.xlsx", 10_000),
        (urls["dem_n06e080"], RAW / "copdem_n06e080.tif", 1_000_000),
        (urls["dem_n06e081"], RAW / "copdem_n06e081.tif", 1_000_000),
        (
            urls["chirps_1981_2024_mean_annual"],
            RAW / "chirps_1981_2024_mean_annual.tif",
            1_000_000,
        ),
        (urls["worldcover_n06e078"], RAW / "worldcover_2021_n06e078.tif", 1_000_000),
        (urls["worldcover_n06e081"], RAW / "worldcover_2021_n06e081.tif", 1_000_000),
        (urls["nasa_glc_csv"], RAW / "nasa_global_landslide_catalog.csv", 1_000_000),
    ]
    for url, destination, minimum_bytes in downloads:
        download_file(url, destination, minimum_bytes, args.refresh_downloads)

    download_soilgrids(config, bbox, args.refresh_downloads)
    if not args.skip_osm:
        download_osm(bbox, args.refresh_downloads)
    verify_input_checksums(args.accept_source_updates)
    build_manifest()


if __name__ == "__main__":
    main()
