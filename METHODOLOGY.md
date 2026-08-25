# Implemented LS-LRSI method

This is implementation documentation for the codebase; it does not replace the assessment report's literature review or local expert justification of the weights.

## Calculation

For each 30 m cell, continuous physical indicator `x` is scaled against the committed baseline:

`I(x) = clip((x - P2_baseline) / (P98_baseline - P2_baseline), 0, 1)`.

The 30 m physical susceptibility is:

`S_cell = 100 × Σ(w_i × I_i)`.

The GN score combines both widespread and locally concentrated susceptibility:

`S_GN = 0.60 × mean(S_cell) + 0.40 × P90(S_cell)`.

GN exposure is a weighted sum of normalised population density, housing density, vulnerable-population share and critical-amenity density. The final score is:

`LS-LRSI_GN = 100 × (S_GN / 100)^0.70 × (E_GN / 100)^0.30`.

Classes are within-Haldummulla quartiles, so they must not be treated as national or operational thresholds. Equal scores are always assigned to the same class; the result does not depend on source row order.

## Pseudocode

```text
load verified source files and committed normalisation baseline
reproject and resample physical inputs to EPSG:5235 at 30 m
reject an input with more than 0.5% missing study-area coverage
fill remaining small gaps from the nearest valid cell
write a preprocessing audit of missing coverage, filled cells and P2/P98 clipping
derive slope and 1 km local relief from the DEM
normalise indicators using fixed P2/P98 baseline bounds
calculate the weighted 30 m susceptibility surface
summarise susceptibility by GN (0.6 mean + 0.4 P90)
normalise GN exposure fields with their fixed baseline bounds
calculate geometric susceptibility-exposure risk score
assign relative GN quartile classes and run weight sensitivity analysis
write maps, tables, rasters, vectors and provenance metadata
```

## Reuse rule

Routine future updates must reuse `config/normalization_baseline.json`; this preserves score comparability with the baseline assessment. Recalculate that file only when the study area, input definitions, or index methodology have intentionally changed and the revised method has been reviewed.

## Assumption boundary

The weighting, WorldCover class scores and road/stream decay distances are provisional expert-judgement choices. They are intentionally interpretable but are not calibrated landslide probabilities. Mean annual CHIRPS rainfall represents broad climatological wetness at an effective 0.05-degree native resolution; the 30 m aligned raster must not be interpreted as local 30 m rainfall measurement. Event-based rainfall, geology and a field-verified inventory are priority extensions rather than hidden assumptions in the baseline score.
