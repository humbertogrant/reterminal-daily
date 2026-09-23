from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
REQUIRED = {"UST_2Y", "UST_10Y", "REAL_10Y", "SP500", "ACWI", "MONEX"}
ALLOWED = {"verified", "fallback_verified", "stale_last_good", "unavailable"}


def main() -> None:
    manifest = json.loads((OUT / "latest_manifest.json").read_text(encoding="utf-8"))
    markets = manifest.get("markets", {})

    assert set(markets) == REQUIRED, f"Expected six markets, got {set(markets)}"
    for name, item in markets.items():
        assert item.get("source"), f"{name}: missing source"
        assert item.get("source_status") in ALLOWED, f"{name}: invalid source status"
        if item["source_status"] != "unavailable":
            assert item.get("observation_date"), f"{name}: missing observation_date"
            assert item.get("value") is not None, f"{name}: missing value"

    image = Image.open(OUT / "latest.png")
    assert image.size == (800, 480), f"Wrong PNG size: {image.size}"

    svg = (OUT / "latest.svg").read_text(encoding="utf-8")
    assert 'clipPath id="narrativeClip"' in svg, "Narrative clipping guard missing"
    assert 'width="800" height="480"' in svg, "SVG canvas is not 800x480"

    font_sizes = [float(x) for x in re.findall(r'font-size="([0-9.]+)"', svg)]
    assert font_sizes and min(font_sizes) >= 8, "Typography fell below 8 px"

    print("Acceptance PASS: six markets, manifest, SVG guards, PNG 800x480.")


if __name__ == "__main__":
    main()
