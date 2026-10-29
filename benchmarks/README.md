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
| [RKQGRPoDV_I](https://youtu.be/RKQGRPoDV_I) | v1.4 | 0.22 (p = 0.029) | 0.42 | 2/5 | 0.17 / 0.16 | raw JSON |

RKQGRPoDV_I (30,203 comments): comments alone reach ρ 0.53, but captions run negative (ρ −0.25), which pulls the fused curve down. A raw comments-only blend scores ρ 0.53 with 4/5 peaks. That comes from one video in-sample, so it's a lead, not a new set of weights.

\* The v1.3 data was digitised from exported PNGs, not raw JSON. The listed top-5 and drop-off scores are exact; the other bins are read from the plotted curve to within about ±0.02. The mean and hot-segment share match the export summary. Later entries use raw JSON exports.

Note that p-values treat bins as independent. Neighbouring bins are autocorrelated, so the p-values are optimistic.

## Accuracy vs engagement

`band_plot.py` plots how accuracy changes with a video's comment count. Add a `meta.json` next to each pair (`{"comments": 6598, "views": 2900000, "genre": "gaming"}`), then run:

```bash
python benchmarks/band_plot.py v1.4 gaming
```

It writes `accuracy_vs_engagement.png` and a CSV with two scores per video:

- **Peak accuracy %**: the share of YouTube's top-5 peaks the estimate finds within ±15 s.
- **Ranking accuracy %**: the share of segment pairs the estimate orders the same way as YouTube, which is (Kendall τ + 1) / 2. 50% is chance and 100% is perfect.

### Gaming engagement set (counts read 2026-10-29)

| Video | Comments | Views | Length |
|---|---|---|---|
| [RKQGRPoDV_I](https://youtu.be/RKQGRPoDV_I) | 30,203 | 24M | 33:24 |
| [dpFpRBt90W0](https://youtu.be/dpFpRBt90W0) | 8,856 | 2.2M | 31:14 |
| [arWClcUVxm8](https://youtu.be/arWClcUVxm8) | 6,598 | 2.9M | 40:26 |
| [kYhb7w2GNIs](https://youtu.be/kYhb7w2GNIs) | 2,229 | 1.7M | 55:42 |
| [vCohhCaxJdM](https://youtu.be/vCohhCaxJdM) | 447 | 371K | 38:31 |
| [ScTGNr6zSIE](https://youtu.be/ScTGNr6zSIE) | 161 | 184K | 45:47 |

Each folder already has its `meta.json`; drop `official.json` and `estimated.json` into `<id>/v1.4/` and run `band_plot.py`.

### Controlled sets (counts read 2026-10-29)

Views vary while comments stay about the same (~3.6k–4.2k): [rMvqiIWGZ5g](https://youtu.be/rMvqiIWGZ5g) 4M / 3,923 · [ijsSF33ffHw](https://youtu.be/ijsSF33ffHw) 2.9M / 4,242 · [OsO3A5tsyW4](https://youtu.be/OsO3A5tsyW4) 677K / 3,606

Comments vary while views stay about the same (~1.9M–2.9M): [dpFpRBt90W0](https://youtu.be/dpFpRBt90W0) 2.2M / 8,856 · [ijsSF33ffHw](https://youtu.be/ijsSF33ffHw) 2.9M / 4,242 · [hOAJ7LN8IiQ](https://youtu.be/hOAJ7LN8IiQ) 1.9M / 1,701
