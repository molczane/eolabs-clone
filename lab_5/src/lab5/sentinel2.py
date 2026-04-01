from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from src.lab5.envi_utils import parse_map_info


PLANETARY_COMPUTER_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
SENTINEL2_COLLECTION = "sentinel-2-l2a"
SENTINEL2_REQUIRED_BANDS = ("B03", "B04", "B05", "B06", "B08", "B11")

SENTINEL2_BAND_ALIASES = {
    "B02": ("B02", "blue"),
    "B03": ("B03", "green"),
    "B04": ("B04", "red"),
    "B05": ("B05",),
    "B06": ("B06",),
    "B08": ("B08", "nir", "nir08"),
    "B8A": ("B8A", "nir08"),
    "B11": ("B11", "swir16"),
}


@dataclass(frozen=True)
class TargetGrid:
    crs: Any
    transform: Any
    width: int
    height: int
    bounds: tuple[float, float, float, float]


def _import_catalog_clients():
    import planetary_computer
    import pystac_client

    return planetary_computer, pystac_client


def _import_rasterio():
    import rasterio
    from rasterio.crs import CRS
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject, transform_bounds

    return rasterio, CRS, from_origin, Resampling, reproject, transform_bounds


def _coerce_target_date(target_date: str | date | datetime) -> date:
    if isinstance(target_date, datetime):
        return target_date.date()
    if isinstance(target_date, date):
        return target_date
    return date.fromisoformat(str(target_date))


def _scene_crs_from_envi(scene_metadata: Mapping[str, Any]):
    _, CRS, _, _, _, _ = _import_rasterio()
    coordinate_system = scene_metadata.get("coordinate system string")
    if not coordinate_system:
        raise ValueError("ENVI metadata is missing 'coordinate system string'.")
    if isinstance(coordinate_system, (list, tuple, np.ndarray)):
        wkt = ",".join(str(part) for part in coordinate_system).strip()
    else:
        wkt = str(coordinate_system).strip()
    if wkt.startswith("{") and wkt.endswith("}"):
        wkt = wkt[1:-1]
    try:
        return CRS.from_wkt(wkt)
    except Exception:
        import pyproj

        normalized_wkt = pyproj.CRS.from_wkt(wkt).to_wkt()
        return CRS.from_wkt(normalized_wkt)


def scene_grid_from_envi(scene_metadata: Mapping[str, Any]) -> TargetGrid:
    _, _, from_origin, _, _, _ = _import_rasterio()

    map_info = parse_map_info(dict(scene_metadata))
    if map_info is None:
        raise ValueError("ENVI metadata is missing usable 'map info'.")

    width = int(str(scene_metadata["samples"]).strip())
    height = int(str(scene_metadata["lines"]).strip())
    pixel_width = abs(map_info.pixel_width)
    pixel_height = abs(map_info.pixel_height)

    left = map_info.origin_x + (map_info.x_start - map_info.ref_pixel_x - 0.5) * pixel_width
    top = map_info.origin_y - (map_info.y_start - map_info.ref_pixel_y - 0.5) * pixel_height
    transform = from_origin(left, top, pixel_width, pixel_height)
    bounds = (
        left,
        top - height * pixel_height,
        left + width * pixel_width,
        top,
    )

    return TargetGrid(
        crs=_scene_crs_from_envi(scene_metadata),
        transform=transform,
        width=width,
        height=height,
        bounds=bounds,
    )


def scene_bbox_wgs84_from_envi(scene_metadata: Mapping[str, Any]) -> tuple[float, float, float, float]:
    _, CRS, _, _, _, transform_bounds = _import_rasterio()

    grid = scene_grid_from_envi(scene_metadata)
    return tuple(
        transform_bounds(
            grid.crs,
            CRS.from_epsg(4326),
            *grid.bounds,
            densify_pts=21,
        )
    )


def open_catalog(url: str = PLANETARY_COMPUTER_STAC_URL):
    planetary_computer, pystac_client = _import_catalog_clients()
    return pystac_client.Client.open(
        url,
        modifier=planetary_computer.sign_inplace,
    )


def _item_datetime(item) -> datetime:
    dt = getattr(item, "datetime", None)
    if isinstance(dt, datetime):
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

    raw = item.properties.get("datetime") or item.properties.get("start_datetime")
    if raw is None:
        raise ValueError(f"STAC item '{item.id}' is missing a datetime property.")

    parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def search_s2_items(
    bbox: tuple[float, float, float, float],
    target_date: str | date | datetime,
    day_window: int = 5,
    cloud_limit: float = 20.0,
    catalog=None,
) -> list[Any]:
    target = _coerce_target_date(target_date)
    start = target - timedelta(days=int(day_window))
    end = target + timedelta(days=int(day_window))

    if catalog is None:
        catalog = open_catalog()

    search = catalog.search(
        collections=[SENTINEL2_COLLECTION],
        bbox=bbox,
        datetime=f"{start.isoformat()}/{end.isoformat()}",
        query={"eo:cloud_cover": {"lt": float(cloud_limit)}},
    )
    items = list(search.items())
    return sorted(items, key=lambda item: score_item(item, target))


def score_item(item, target_date: str | date | datetime) -> tuple[int, float, str, str]:
    target = _coerce_target_date(target_date)
    item_dt = _item_datetime(item)
    cloud_cover = float(item.properties.get("eo:cloud_cover", 100.0))
    days_from_target = abs((item_dt.date() - target).days)
    return (
        days_from_target,
        cloud_cover,
        item_dt.isoformat(),
        str(item.id),
    )


def select_best_item(items: list[Any], target_date: str | date | datetime):
    if not items:
        raise ValueError("No Sentinel-2 items available for selection.")
    return min(items, key=lambda item: score_item(item, target_date))


def describe_item(item, target_date: str | date | datetime) -> dict[str, Any]:
    item_dt = _item_datetime(item)
    target = _coerce_target_date(target_date)
    return {
        "id": item.id,
        "datetime": item_dt.isoformat(),
        "days_from_target": abs((item_dt.date() - target).days),
        "eo_cloud_cover": float(item.properties.get("eo:cloud_cover", np.nan)),
        "platform": item.properties.get("platform", ""),
        "mgrs_tile": item.properties.get("s2:mgrs_tile", ""),
    }


def _asset_for_band(item, band_name: str):
    aliases = SENTINEL2_BAND_ALIASES.get(band_name, (band_name,))

    for alias in aliases:
        asset = item.assets.get(alias)
        if asset is not None:
            return asset

    for asset in item.assets.values():
        if asset.extra_fields.get("title") in aliases:
            return asset

        eo_bands = asset.extra_fields.get("eo:bands", [])
        raster_bands = asset.extra_fields.get("raster:bands", [])
        for band in eo_bands + raster_bands:
            common_name = band.get("common_name")
            name = band.get("name")
            if common_name in aliases or name in aliases:
                return asset

    raise KeyError(f"Band '{band_name}' not found. Available assets: {list(item.assets.keys())}")


def get_asset_href(item, band_name: str) -> str:
    return str(_asset_for_band(item, band_name).href)


def _asset_scale_offset(asset, array: np.ndarray) -> tuple[float, float]:
    for extra_key in ("raster:bands", "eo:bands"):
        bands = asset.extra_fields.get(extra_key, [])
        if bands:
            scale = bands[0].get("scale")
            offset = bands[0].get("offset")
            if scale is not None or offset is not None:
                return float(scale if scale is not None else 1.0), float(offset if offset is not None else 0.0)

    finite_values = array[np.isfinite(array)]
    if finite_values.size and float(np.nanmax(finite_values)) > 2.0:
        return 0.0001, 0.0
    return 1.0, 0.0


def reproject_to_grid(
    href: str,
    target_crs,
    target_transform,
    width: int,
    height: int,
    resampling=None,
):
    rasterio, _, _, Resampling, reproject, _ = _import_rasterio()

    if resampling is None:
        resampling = Resampling.bilinear

    out = np.zeros((height, width), dtype=np.float32)
    with rasterio.open(href) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=out,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=target_transform,
            dst_crs=target_crs,
            resampling=resampling,
            src_nodata=src.nodata,
            dst_nodata=0.0,
        )
    return out


def download_band(
    item,
    band_name: str,
    save_dir: Path | str,
    target_grid: TargetGrid,
) -> Path:
    rasterio, _, _, _, _, _ = _import_rasterio()

    save_path = Path(save_dir)
    save_path.mkdir(parents=True, exist_ok=True)
    local_path = save_path / f"{item.id}__{band_name}.tif"
    if local_path.exists():
        return local_path

    asset = _asset_for_band(item, band_name)
    arr = reproject_to_grid(
        str(asset.href),
        target_grid.crs,
        target_grid.transform,
        target_grid.width,
        target_grid.height,
    )
    scale, offset = _asset_scale_offset(asset, arr)
    valid_mask = np.isfinite(arr) & (arr != 0.0)
    arr = arr.astype(np.float32, copy=False)
    arr[valid_mask] = np.clip(arr[valid_mask] * scale + offset, 0.0, 1.0)

    with rasterio.open(
        local_path,
        "w",
        driver="GTiff",
        height=target_grid.height,
        width=target_grid.width,
        count=1,
        dtype="float32",
        crs=target_grid.crs,
        transform=target_grid.transform,
        nodata=0.0,
    ) as dst:
        dst.write(arr, 1)

    return local_path


def load_local_stack(band_files: Mapping[str, Path | str]) -> dict[str, np.ndarray]:
    rasterio, _, _, _, _, _ = _import_rasterio()

    stack: dict[str, np.ndarray] = {}
    for band_name, path in band_files.items():
        with rasterio.open(path) as src:
            stack[band_name] = src.read(1).astype(np.float32)
    return stack


__all__ = [
    "PLANETARY_COMPUTER_STAC_URL",
    "SENTINEL2_BAND_ALIASES",
    "SENTINEL2_COLLECTION",
    "SENTINEL2_REQUIRED_BANDS",
    "TargetGrid",
    "describe_item",
    "download_band",
    "get_asset_href",
    "load_local_stack",
    "open_catalog",
    "reproject_to_grid",
    "scene_bbox_wgs84_from_envi",
    "scene_grid_from_envi",
    "score_item",
    "search_s2_items",
    "select_best_item",
]
