# Verified data register

The exact downloaded files, byte sizes and SHA-256 hashes are stored in `data/raw/download_manifest.json`. Expected source hashes are committed in `config/input_checksums.json` and verified before the manifest is written. The analysis does not treat a successful download as proof of suitability; the limits below must be retained in the report.

| Local file | Provider and direct source | Native detail | Coverage used | Analysis role | Verification / caution |
|---|---|---|---|---|---|
| `dcs_haldummulla_gn_population_2024.geojson` | Sri Lanka Department of Census and Statistics, official ArcGIS FeatureServer query: https://services6.arcgis.com/v2E6mIH6KqVu8t9L/arcgis/rest/services/GND_POP_DATA_update/FeatureServer/0 | GN polygons and attributes, EPSG:4326 | Haldummulla DSD; 39 GNs | Boundary, population and age fields | Cross-checked with the official CPH 2024 table structure; provisional GN figures |
| `dcs_gn_population_2024.xlsx` | DCS CPH 2024: https://www.statistics.gov.lk/Population/StaticalInformation/CPH2024/GN_population_excel | GN table | 2024 census moment | Census cross-check | Official provisional table |
| `dcs_gn_housing_2024.xlsx` | DCS CPH 2024: https://www.statistics.gov.lk/Population/StaticalInformation/CPH2024/GN_housing_excel | GN table | 2024 | Occupied housing exposure | Does not record structural vulnerability |
| `copdem_n06e080.tif`, `copdem_n06e081.tif` | Copernicus DEM GLO-30 public S3 tiles; documentation: https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM | Approx. 30 m, EPSG:4326, elevation in metres | Two 1-degree tiles | Slope and 1 km local relief | Digital surface model, not bare-earth ground survey |
| `chirps_1981_2024_mean_annual.tif` | UCSB Climate Hazards Center: https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_annual/tifs/chirps-v2.0.1981-2024.44yrs.tif | 0.05 degrees; mm/year | Mean annual rainfall 1981-2024 | Long-term rainfall indicator | Native grid is much coarser than 30 m; not storm intensity |
| `worldcover_2021_n06e078.tif`, `worldcover_2021_n06e081.tif` | ESA WorldCover 2021 v200 public S3; documentation: https://worldcover2021.esa.int/documentation | 10 m, EPSG:4326 | 2021 | Land-cover contribution | Reported global overall accuracy 76.7%; local checking is recommended |
| `soilgrids_clay_0_5cm_mean_250m.tif` | ISRIC SoilGrids 2.0 WCS: https://maps.isric.org/mapserv?map=/map/clay.map | 250 m; modelled clay mean at 0-5 cm; g/kg | Static model layer | Surface clay proxy | Converted from g/kg to mass percent; not a geotechnical strength layer |
| `osm_roads.json`, `osm_waterways.json`, `osm_critical_amenities.json` | OpenStreetMap via Overpass API; licence: https://www.openstreetmap.org/copyright | Vector geometry and tags | Retrieval date recorded by manifest | Proximity and facility exposure | Community mapping can be incomplete; attribution required |
| `nasa_global_landslide_catalog.csv` | NASA legacy export: https://data.nasa.gov/docs/legacy/Global_Landslide_Catalog_Export/Global_Landslide_Catalog_Export_rows.csv | Report points; positional accuracy field | Export current to 7 March 2016 | Limited independent check | 75 Sri Lanka records, 3 keyword candidates and only 2 inside Haldummulla; unsuitable for supervised training |

## Source selection decision

NBRO hazard-zonation products should be used as an external professional benchmark if suitable local map sheets and permission are obtained. They were not used as a training layer because the current reproducible pipeline did not obtain an official machine-readable NBRO vector or raster service. This avoids digitising a web image and presenting it as primary data.

## Rainfall interpretation and future extension

The baseline CHIRPS layer is a static climatological indicator. Its 0.05-degree native grid is approximately 5 km around Haldummulla, and resampling it to the common 30 m grid only aligns cells for calculation. It does not add local rainfall detail. A future dynamic version should derive one internally coherent rainfall sub-index from dated daily rainfall, such as maximum 1-day, 3-day or 7-day accumulation and antecedent 7-day or 30-day rainfall. Those variables should be calibrated against a field-verified, dated inventory and checked for correlation before receiving separate weights.

