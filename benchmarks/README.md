# Benchmarks: official vs estimated

These compare Heatmapify's estimate with YouTube's official "Most replayed" curve, one video per folder.

```
benchmarks/<video_id>/<version>/
  official.json    dashboard Export → JSON, normal mode (official data)
  estimated.json   dashboard Export → JSON, forced-estimate mode
  figure.png       output of compare_fig.py
```

## Reproduce

```bash
pip install numpy scipy matplotlib
python benchmarks/compare_fig.py official.json estimated.json figure.png
```

Before comparing, estimated windows are resampled onto the official bin grid with overlap-weighted means. The script reports Pearson, Spearman and Kendall correlations, MAE/RMSE, mean, median and hot-bin share (score ≥ 0.6), top-5 peak recall within ±15 s, and per-signal Spearman when the export includes signal scores. Without signal scores it shows score ECDFs with a KS test instead.

Optional environment variables: `FIG_LABEL` replaces the title label, and `FIG_NOTE` adds text to the footnote.

## Results

| Video | Version | Spearman ρ | Pearson r | Top-5 peak recall | Mean (official / est.) | Data |
|---|---|---|---|---|---|---|
| [IKPJq5Z_1ZM](https://youtu.be/IKPJq5Z_1ZM) | v1.3 | 0.41 (p < 0.001) | 0.41 | 3/5 | 0.12 / 0.50 | digitised* |

\* The v1.3 data was digitised from exported PNGs, not raw JSON. The listed top-5 and drop-off scores are exact; the other bins are read from the plotted curve to within about ±0.02. The mean and hot-segment share match the export summary. Later entries use raw JSON exports.

Note that p-values treat bins as independent. Neighbouring bins are autocorrelated, so the p-values are optimistic.
