from __future__ import annotations

import json
from pathlib import Path


def load_polygon(path: Path) -> list[tuple[float, float]]:
    feature = json.loads(path.read_text(encoding="utf-8"))
    geometry = feature["geometry"]
    coords = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        ring = coords[0]
    elif geometry["type"] == "MultiPolygon":
        ring = max((poly[0] for poly in coords), key=len)
    else:
        raise ValueError(f"Unsupported geometry: {geometry['type']}")
    return [(float(lon), float(lat)) for lon, lat in ring]


def project(
    points: list[tuple[float, float]],
    viewport: list[float],
    x: float,
    y: float,
    width: float,
    height: float,
) -> list[tuple[float, float]]:
    min_lon, min_lat, max_lon, max_lat = viewport
    result = []
    for lon, lat in points:
        px = x + (lon - min_lon) / (max_lon - min_lon) * width
        py = y + height - (lat - min_lat) / (max_lat - min_lat) * height
        result.append((px, py))
    return result


def svg_path(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    head, *tail = points
    commands = [f"M {head[0]:.1f} {head[1]:.1f}"]
    commands += [f"L {x:.1f} {y:.1f}" for x, y in tail]
    commands.append("Z")
    return " ".join(commands)
