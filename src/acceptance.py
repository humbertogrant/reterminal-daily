from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
REQUIRED = {"UST_2Y", "UST_10Y", "REAL_10Y", "SP500", "ACWI", "MONEX"}
ALLOWED = {"verified", "fallback_verified", "stale_last_good", "unavailable"}


def assert_png(name: str) -> None:
    image = Image.open(OUT / name)
    assert image.size == (800, 480), f"{name}: wrong PNG size {image.size}"


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
            if item.get("previous_value") is not None:
                assert item.get("delta") is not None, f"{name}: previous value without delta"

    quality = manifest.get("data_quality", {})
    status = quality.get("status")
    assert status in {"PASS", "PASS_DEGRADED", "FAIL"}, f"Unknown quality state: {status}"
    if status == "FAIL":
        raise AssertionError(
            "Data quality FAIL: " + "; ".join(quality.get("fatal_reasons", []))
        )
    if status == "PASS_DEGRADED":
        print(
            "::warning title=E1001 data quality::"
            + "; ".join(quality.get("reasons", []))
        )

    assert_png("latest.png")
    assert_png("japanese_test.png")

    svg = (OUT / "latest.svg").read_text(encoding="utf-8")
    jp_svg = (OUT / "japanese_test.svg").read_text(encoding="utf-8")

    assert 'clipPath id="narrativeClip"' in svg, "Narrative clipping guard missing"
    assert 'width="800" height="480"' in svg, "SVG canvas is not 800x480"
    assert "Noto Sans CJK JP" in svg, "Japanese-capable font family missing"
    assert "sin dato" not in svg.lower(), "Unavailable date text leaked into SVG"

    assert "JAPONÉS · N5" in jp_svg, "Forced Japanese test did not render Japanese mode"
    assert "いちばん" in jp_svg, "Japanese prompt missing"
    assert "この本がいちばん高いです。" in jp_svg, "Japanese answer missing"
    assert "Noto Sans CJK JP" in jp_svg, "Japanese test lacks CJK font family"

    # Avoid editorially meaningless negative zero.
    assert "-0.00%" not in svg, "Negative zero leaked into production SVG"
    assert "-0.00%" not in jp_svg, "Negative zero leaked into Japanese test SVG"

    font_sizes = [float(x) for x in re.findall(r'font-size="([0-9.]+)"', svg)]
    assert font_sizes and min(font_sizes) >= 8, "Typography fell below 8 px"

    print(
        f"Acceptance PASS: quality={status}; latest + Japanese test 800x480; "
        "SVG guards and zero normalization present."
    )


if __name__ == "__main__":
    main()
