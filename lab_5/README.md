# Hyperspectral BSQ Viewer

A minimal desktop tool for exploring ENVI/BSQ hyperspectral data cubes. The
repository is being extended into a full Lab 5 workflow for spectral-library
collection, airborne water-quality analysis, Sentinel-2 comparison, and SAM.

## Features

- Loads any ENVI/BSQ image from `data/images/` (reads the `.hdr` sidecar for metadata)
- Displays an RGB preview using the bands declared in `default_bands` of the header
- Click any pixel to see its full spectral signature as a chart
- Drag a rectangle ROI to inspect its mean spectrum and variability
- Export the selected pixel spectrum to a two-column CSV (`wavelength_nm`, `value`)
- Export ROI samples directly into `data/spectral_library/` with class labels and notes

## Requirements

Python 3.10+ and the packages listed in `requirements.txt`.

## Installation

```bash
pip install -r requirements.txt
```

If you are using conda:

```bash
conda install -c conda-forge numpy matplotlib
pip install spectral
```

## Running

```bash
# auto-detect dataset in data/images/
python3 viewer.py

# open a specific file directly
python3 viewer.py data/images/221000_Odra_HS_Blok_A_008_VS_join_atm.hdr
```

On startup the tool will:

1. Scan `data/images/` for `.hdr` files.
2. If only one is found it opens immediately; if multiple are found a small picker dialog appears.
3. The RGB preview loads (reads 3 bands — fast even for large cubes).
4. Click any pixel → its spectral signature appears on the right.
5. Drag a rectangle ROI → the mean ROI spectrum and standard deviation appear on the right.
6. Click **Export pixel spectrum to CSV…** to save the current pixel spectrum.
7. Click **Export ROI sample…** to save the ROI into the spectral-library structure.

## ROI Workflow

The ROI workflow is the main path for building the Lab 5 spectral library.

1. Open a scene in the viewer.
2. Drag a rectangle over a representative land-cover patch.
3. Review the ROI bounds and valid-pixel count shown in the status text.
4. Click **Export ROI sample…**.
5. Enter a class label such as `water`, `forest`, or `green vegetation`.
6. Optionally add notes describing the sample.

Exports are written to:

- `data/spectral_library/raw/<class_name>/<sample_id>.csv`
- `data/spectral_library/catalog.csv`

## Project Layout

- `viewer.py`: desktop viewer for browsing ENVI/BSQ scenes
- `src/lab5/`: reusable processing code shared by the viewer and notebook
- `scripts/`: command-line utilities such as spectral-library rebuild scripts
- `notebooks/`: analysis notebooks for airborne and Sentinel-2 workflows
- `data/images/`: input ENVI scenes
- `data/spectral_library/`: exported ROI samples, catalog, and class summaries
- `data/sentinel2/`: cached Sentinel-2 downloads
- `data/outputs/`: generated plots, tables, and comparison outputs

## Data format assumptions

The tool reads standard ENVI headers (`.hdr` + `.bsq` pairs). The following header keys are used when present:

| Key | Purpose |
|---|---|
| `samples`, `lines`, `bands` | Image dimensions |
| `data type` | Pixel data type (e.g. `2` = int16) |
| `byte order` | Endianness |
| `interleave` | Must be `BSQ` |
| `default bands` | 1-based RGB band indices for preview |
| `wavelength` | Per-band wavelengths (nm) for the X axis |
| `data ignore value` | No-data threshold; masked in both RGB and spectrum |
| `reflectance scale factor` | Informational only (not applied automatically) |

To adapt the tool to a different sensor, edit `get_rgb_bands()` and
`FALLBACK_RGB` in `src/lab5/envi_utils.py`.

## Notes

- The `.bsq` files are excluded from the repository via `.gitignore` due to their size (7–18 GB each). Download the data from OneDrive and place it in `data/images/`.
- The tool never loads the full cube into RAM. Band reads are memory-mapped by the `spectral` library; reading one pixel's spectrum requires only 456 × 2 bytes of I/O.
