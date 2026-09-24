from __future__ import annotations

import json
from pathlib import Path

from market_dates import CLOSE_DATE_POLICY, edition_date, expected_close_date

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"

SERIES = ("UST_2Y", "UST_10Y", "REAL_10Y", "SP500", "ACWI", "MONEX")
YIELDS = {"UST_2Y", "UST_10Y", "REAL_10Y"}
CORE = {"UST_2Y", "UST_10Y", "REAL_10Y"}


def observations(source: dict, expected: str) -> list[dict]:
    rows = source.get("observations", []) if source else []
    # Apply the ceiling to every tier, including last-good selection, and never
    # treat two entries for the same date as separate daily observations.
    by_date = {
        r["date"]: r for r in rows
        if r.get("date") and r["date"] <= expected and r.get("value") is not None
    }
    return [by_date[day] for day in sorted(by_date)]


def expected_market_date(raw: dict) -> str:
    return expected_close_date(edition_date(raw["retrieved_at"]))


def pick(item: dict, expected: str) -> tuple[str, str, list[dict]]:
    primary = observations(item.get("primary", {}), expected)
    fallback = observations(item.get("fallback", {}), expected)

    def with_previous(history: list[dict]) -> list[dict]:
        current = history[-1]
        # Prefer primary values on overlapping dates; use the fallback to fill
        # history when the primary publishes only one official closing price.
        prior = {
            row["date"]: row for row in fallback + primary
            if row["date"] < current["date"]
        }
        return [prior[max(prior)], current] if prior else [current]

    if primary and primary[-1]["date"] == expected:
        return "primary", item["primary_name"], with_previous(primary)

    if fallback and fallback[-1]["date"] == expected:
        return "fallback", item.get("fallback_name", "fallback"), with_previous(fallback)

    candidates = []
    if primary:
        candidates.append((item["primary_name"], primary))
    if fallback:
        candidates.append((item.get("fallback_name", "fallback"), fallback))
    if candidates:
        source, history = max(candidates, key=lambda x: x[1][-1]["date"])
        return "stale", source, with_previous(history)

    return "unavailable", item.get("primary_name", "unknown"), []


def calc_delta(name: str, value: float, previous: float) -> tuple[float, str]:
    if name in YIELDS:
        return round((value - previous) * 100, 4), "bp"
    return round((value / previous - 1) * 100, 6), "pct"


def reading(markets: dict, expected: str) -> dict:
    def move(name: str) -> float | None:
        delta = markets[name].get("delta")
        return None if delta is None else float(delta["value"])

    facts = []
    y2, r10 = move("UST_2Y"), move("REAL_10Y")
    if y2 is not None and r10 is not None:
        facts.append(f"2Y {y2:+.0f} pb; real 10Y {r10:+.0f} pb.")
    def pct_label(value: float) -> str:
        if abs(value) < 0.005:
            return "0.00%"
        return f"{value:+.2f}%"

    sp, acwi = move("SP500"), move("ACWI")
    if sp is not None and acwi is not None:
        facts.append(f"S&P 500 {pct_label(sp)}; ACWI {pct_label(acwi)}.")
    monex = markets["MONEX"]
    if monex.get("value") is not None:
        facts.append(f"MONEX: {monex['value']:.2f} CRC/USD.")

    misaligned = [
        name
        for name, item in markets.items()
        if item.get("observation_date") and item["observation_date"] != expected
    ]
    interpretation = []
    if misaligned:
        interpretation.append("Hay fechas desalineadas; leer movimientos con cautela.")
    else:
        interpretation.append("Las seis series están alineadas al mismo cierre.")
    interpretation.append("Un solo día no identifica por sí mismo un shock macro.")
    return {"facts": facts[:3], "interpretation": interpretation[:2]}


def assess_quality(markets: dict, expected: str) -> dict:
    reasons = []
    fatal = []

    for name, item in markets.items():
        status = item["source_status"]
        if status == "unavailable":
            reasons.append(f"{name}: unavailable")
            if name in CORE:
                fatal.append(f"{name}: core rate unavailable")
        elif status == "stale_last_good":
            reasons.append(
                f"{name}: stale at {item.get('observation_date')} vs expected {expected}"
            )

        if item.get("value") is not None and item.get("previous_value") is None:
            reasons.append(f"{name}: no previous verified observation")
        elif item.get("value") is not None and item.get("delta") is None:
            reasons.append(f"{name}: delta unavailable")

    if fatal:
        status = "FAIL"
    elif reasons:
        status = "PASS_DEGRADED"
    else:
        status = "PASS"

    return {"status": status, "reasons": reasons, "fatal_reasons": fatal}


def build_manifest(raw: dict) -> dict:
    expected = expected_market_date(raw)
    markets = {}

    for name in SERIES:
        tier, source, history = pick(raw["series"][name], expected)

        if tier == "unavailable" or not history:
            markets[name] = {
                "source": source,
                "source_status": "unavailable",
                "expected_date": expected,
                "observation_date": None,
                "value": None,
                "previous_observation_date": None,
                "previous_value": None,
                "delta": None,
            }
            continue

        current = history[-1]
        previous = history[-2] if len(history) >= 2 else None
        delta = None
        if previous and previous["value"] not in (None, 0):
            value, unit = calc_delta(name, float(current["value"]), float(previous["value"]))
            delta = {"value": value, "unit": unit}

        status = {
            "primary": "verified",
            "fallback": "fallback_verified",
            "stale": "stale_last_good",
        }[tier]

        markets[name] = {
            "source": source,
            "source_status": status,
            "expected_date": expected,
            "observation_date": current["date"],
            "value": float(current["value"]),
            "previous_observation_date": previous["date"] if previous else None,
            "previous_value": float(previous["value"]) if previous else None,
            "delta": delta,
        }

    quality = assess_quality(markets, expected)
    return {
        "retrieved_at": raw["retrieved_at"],
        "edition_date": edition_date(raw["retrieved_at"]),
        "timezone": "America/Costa_Rica",
        "close_date_policy": CLOSE_DATE_POLICY,
        "expected_close_date": expected,
        "data_quality": quality,
        "markets": markets,
        "reading": reading(markets, expected),
    }


def main() -> None:
    raw = json.loads((OUT / "raw.json").read_text(encoding="utf-8"))
    validated = build_manifest(raw)
    serialized = json.dumps(validated, indent=2, ensure_ascii=False)
    (OUT / "validated.json").write_text(serialized, encoding="utf-8")
    (OUT / "latest_manifest.json").write_text(serialized, encoding="utf-8")


if __name__ == "__main__":
    main()
