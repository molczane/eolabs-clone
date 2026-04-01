from __future__ import annotations

from typing import Sequence

import numpy as np

from src.lab5.envi_utils import find_nearest_band


def _as_float_array(values) -> np.ndarray:
    return np.asarray(values, dtype=np.float64)


def _mask_band(band, ignore_value: float | None = None) -> np.ndarray:
    masked = _as_float_array(band).copy()
    if ignore_value is not None:
        masked[masked >= ignore_value] = np.nan
    masked[masked < 0] = np.nan
    return masked


def _read_band(cube_or_reader, band_index: int) -> np.ndarray:
    if hasattr(cube_or_reader, "read_band"):
        return np.asarray(cube_or_reader.read_band(int(band_index)), dtype=np.float64)

    cube = np.asarray(cube_or_reader)
    if cube.ndim != 3:
        raise ValueError("Expected a 3-D cube with shape (rows, cols, bands).")
    return np.asarray(cube[:, :, int(band_index)], dtype=np.float64)


def safe_ratio(numerator, denominator):
    numerator_arr, denominator_arr = np.broadcast_arrays(
        _as_float_array(numerator),
        _as_float_array(denominator),
    )
    result = np.full(numerator_arr.shape, np.nan, dtype=np.float64)
    valid_mask = (
        np.isfinite(numerator_arr)
        & np.isfinite(denominator_arr)
        & (np.abs(denominator_arr) > 1e-12)
    )
    np.divide(
        numerator_arr,
        denominator_arr,
        out=result,
        where=valid_mask,
    )
    return result.item() if result.shape == () else result


def band_by_wavelength(
    cube_or_reader,
    wavelengths: np.ndarray,
    target_nm: float,
    invalid_mask: np.ndarray | None = None,
    ignore_value: float | None = None,
) -> np.ndarray:
    band_index = find_nearest_band(wavelengths, target_nm, invalid_mask)
    return _mask_band(_read_band(cube_or_reader, band_index), ignore_value)


def chlorophyll_red_edge_peak(r665, r705, r740):
    r665_arr = _as_float_array(r665)
    r705_arr = _as_float_array(r705)
    r740_arr = _as_float_array(r740)
    baseline = r665_arr + ((705.0 - 665.0) / (740.0 - 665.0)) * (r740_arr - r665_arr)
    result = r705_arr - baseline
    return result.item() if result.shape == () else result


def ndci(r665, r705):
    return safe_ratio(_as_float_array(r705) - _as_float_array(r665), _as_float_array(r705) + _as_float_array(r665))


def doc_proxy_green_red(r560, r665):
    return safe_ratio(r560, r665)


def ndti(r560, r665):
    return safe_ratio(_as_float_array(r665) - _as_float_array(r560), _as_float_array(r665) + _as_float_array(r560))


def composite_by_wavelengths(
    cube_or_reader,
    wavelengths: np.ndarray,
    targets_nm: Sequence[float],
    invalid_mask: np.ndarray | None = None,
    ignore_value: float | None = None,
) -> np.ndarray:
    if len(targets_nm) != 3:
        raise ValueError("False-color composites require exactly three target wavelengths.")

    channels = [
        band_by_wavelength(
            cube_or_reader,
            wavelengths,
            target_nm,
            invalid_mask=invalid_mask,
            ignore_value=ignore_value,
        )
        for target_nm in targets_nm
    ]
    return np.stack(channels, axis=-1)


def stretch_composite(rgb: np.ndarray) -> np.ndarray:
    rgb_arr = np.asarray(rgb, dtype=np.float64)
    if rgb_arr.ndim != 3 or rgb_arr.shape[2] != 3:
        raise ValueError("RGB composite must have shape (rows, cols, 3).")

    stretched = rgb_arr.copy()
    for channel_idx in range(3):
        channel = stretched[:, :, channel_idx]
        valid_values = channel[np.isfinite(channel)]
        if valid_values.size == 0:
            stretched[:, :, channel_idx] = 0.0
            continue
        lo, hi = np.percentile(valid_values, [2, 98])
        stretched[:, :, channel_idx] = np.clip(
            (channel - lo) / max(hi - lo, 1e-6),
            0.0,
            1.0,
        )

    return np.nan_to_num(stretched, nan=0.0).astype(np.float32)


__all__ = [
    "band_by_wavelength",
    "chlorophyll_red_edge_peak",
    "composite_by_wavelengths",
    "doc_proxy_green_red",
    "ndci",
    "ndti",
    "safe_ratio",
    "stretch_composite",
]
