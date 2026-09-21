# LearnNote brand assets

The LearnNote mark combines an open book, a play symbol, and two note lines.
It uses a flat ink-green, sage and warm-paper palette without gradients so that it remains legible
from a 16 px browser icon to a 512 px application asset.

The refreshed mark has two clean page silhouettes, a wider negative-space spine
and a solid play symbol. The 16 px toolbar variant omits the two note strokes
to avoid noise. The existing programmatic source remains canonical: no AI-made
application screenshots or non-reproducible raster replacements are used.

Run `python scripts/generate-brand-assets.py` from the repository root whenever
the generated PNG or ICO files need to be refreshed.

## Usage

- `learnnote-mark-16.png` through `learnnote-mark-512.png`: product and web marks
- `learnnote.ico`: Windows executable and installer icon
- `palette.json`: canonical flat brand colors and concept metadata

Keep clear space around the mark and do not recolor, stretch, rotate, or add
effects to generated assets.
