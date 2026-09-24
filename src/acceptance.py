from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path

from PIL import Image

from market_dates import edition_date, expected_close_date

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
REQUIRED = {"UST_2Y", "UST_10Y", "REAL_10Y", "SP500", "ACWI", "MONEX"}
ALLOWED = {"verified", "fallback_verified", "stale_last_good", "unavailable"}
YIELDS = {"UST_2Y", "UST_10Y", "REAL_10Y"}


def assert_temporal_contract(manifest: dict) -> None:
    assert manifest.get("close_date_policy") == "previous_us_session", "Unknown close-date policy"
    edition = edition_date(manifest["retrieved_at"])
    assert manifest.get("edition_date") == edition, "Edition date differs from retrieval date in Costa Rica"
    expected = expected_close_date(edition)
    assert manifest.get("expected_close_date") == expected, "Expected close differs from previous US session"
    assert expected < edition, "Expected close must precede the edition"

    def canonical_date(value: object, label: str) -> str:
        assert isinstance(value, str), f"{label}: missing date"
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise AssertionError(f"{label}: invalid date {value!r}") from exc
        assert parsed.isoformat() == value, f"{label}: date must use YYYY-MM-DD"
        return value

    def finite_number(value: object, label: str) -> float:
        assert isinstance(value, (int, float)) and not isinstance(value, bool), f"{label}: invalid number"
        assert math.isfinite(value), f"{label}: non-finite number"
        return float(value)

    for name, item in manifest.get("markets", {}).items():
        assert item.get("expected_date") == expected, f"{name}: inconsistent expected date"
        status = item.get("source_status")
        if status == "unavailable":
            for field in ("observation_date", "value", "previous_observation_date", "previous_value", "delta"):
                assert item.get(field) is None, f"{name}: unavailable series contains {field}"
            continue

        observed = canonical_date(item.get("observation_date"), f"{name}: observation")
        assert observed <= expected, f"{name}: observation {observed} is after expected close {expected}"
        if status in {"verified", "fallback_verified"}:
            assert observed == expected, f"{name}: verified observation is not the expected close"
        elif status == "stale_last_good":
            assert observed < expected, f"{name}: stale observation is not older than expected close"

        current = finite_number(item.get("value"), f"{name}: value")
        previous_date = item.get("previous_observation_date")
        previous_value = item.get("previous_value")
        delta = item.get("delta")
        if previous_date is None and previous_value is None:
            assert delta is None, f"{name}: delta without a previous observation"
            continue

        previous_date = canonical_date(previous_date, f"{name}: previous observation")
        assert previous_date < observed, f"{name}: previous observation must strictly precede current observation"
        previous = finite_number(previous_value, f"{name}: previous value")
        assert previous != 0, f"{name}: zero previous value cannot support the stored delta"
        assert isinstance(delta, dict), f"{name}: previous observation without delta"
        actual_delta = finite_number(delta.get("value"), f"{name}: delta")
        if name in YIELDS:
            calculated = round((current - previous) * 100, 4)
            unit = "bp"
        else:
            calculated = round((current / previous - 1) * 100, 6)
            unit = "pct"
        assert delta.get("unit") == unit, f"{name}: incorrect delta unit"
        assert math.isclose(actual_delta, calculated, rel_tol=0, abs_tol=1e-9), f"{name}: delta does not match current and previous values"


def assert_png(name: str) -> None:
    image = Image.open(OUT / name)
    assert image.size == (800, 480), f"{name}: wrong PNG size {image.size}"


def main() -> None:
    manifest = json.loads((OUT / "latest_manifest.json").read_text(encoding="utf-8"))
    assert_temporal_contract(manifest)
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
