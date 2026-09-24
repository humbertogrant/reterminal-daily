"""Regressions for selecting a completed close for the daily CR edition."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import acceptance
import market_dates
import retrieve
import validate


def source(*rows: tuple[str, float]) -> dict:
    return {"ok": True, "observations": [{"date": day, "value": value} for day, value in rows]}


def september_24_raw() -> dict:
    """Small reproduction of the intraday ACWI contamination from run #17."""
    closes = {
        "UST_2Y": (4.71, 4.85),
        "UST_10Y": (4.96, 5.11),
        "REAL_10Y": (2.63, 2.76),
        "SP500": (7764.64, 7706.03),
        "ACWI": (162.20, 160.22),
        "MONEX": (451.79, 453.60),
    }
    raw = {"retrieved_at": "2026-09-24T14:28:17+00:00", "series": {}}
    for name, (previous, current) in closes.items():
        raw["series"][name] = {
            "primary_name": f"{name} official",
            "primary": source(("2026-09-22", previous), ("2026-09-23", current)),
        }
    # iShares supplies one official close; its earlier close must be recovered
    # from history even when the fallback includes today's live price.
    raw["series"]["ACWI"].update({
        "primary": source(("2026-09-23", 160.22)),
        "fallback_name": "ACWI historical fallback",
        "fallback": source(
            ("2026-09-22", 162.20),
            ("2026-09-23", 160.22),
            ("2026-09-24", 159.59),
        ),
    })
    return raw


class EditionCalendarTests(unittest.TestCase):
    def test_costa_rica_midnight_defines_edition_date(self):
        self.assertEqual(market_dates.edition_date("2026-09-24T05:59:59+00:00"), "2026-09-23")
        self.assertEqual(market_dates.edition_date("2026-09-24T06:00:00+00:00"), "2026-09-24")
        self.assertEqual(market_dates.edition_date("2026-09-24T00:00:00-06:00"), "2026-09-24")

    def test_retrieval_timestamp_must_include_timezone(self):
        for timestamp in ("2026-09-24T14:28:17", "2026-09-24", "not-a-timestamp"):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                market_dates.edition_date(timestamp)

    def test_previous_session_respects_weekends_and_exchange_holidays(self):
        for edition, expected in (
            ("2026-09-24", "2026-09-23"),
            ("2026-09-28", "2026-09-25"),
            ("2026-09-08", "2026-09-04"),  # Labor Day
            ("2026-04-06", "2026-04-02"),  # Good Friday
            ("2026-01-02", "2025-12-31"),  # New Year's Day
        ):
            with self.subTest(edition=edition):
                self.assertEqual(market_dates.expected_close_date(edition), expected)

    def test_delayed_afternoon_edition_still_uses_previous_session(self):
        raw = september_24_raw()
        raw["retrieved_at"] = "2026-09-24T23:30:00+00:00"
        self.assertEqual(validate.expected_market_date(raw), "2026-09-23")

    def test_expected_close_does_not_depend_on_source_dates_or_availability(self):
        raw = september_24_raw()
        raw["series"] = {}
        self.assertEqual(validate.expected_market_date(raw), "2026-09-23")
        raw["series"]["ACWI"] = {"primary": source(("2099-12-31", 999.0))}
        self.assertEqual(validate.expected_market_date(raw), "2026-09-23")


class SourceSelectionTests(unittest.TestCase):
    def test_intraday_acwi_is_excluded_and_official_close_gets_previous_value(self):
        raw = september_24_raw()
        original = deepcopy(raw)
        manifest = validate.build_manifest(raw)
        self.assertEqual(raw, original, "Building a manifest must not mutate retrieval data")
        self.assertEqual(manifest["edition_date"], "2026-09-24")
        self.assertEqual(manifest["expected_close_date"], "2026-09-23")
        self.assertEqual(manifest["data_quality"]["status"], "PASS")
        acwi = manifest["markets"]["ACWI"]
        self.assertEqual(acwi["source_status"], "verified")
        self.assertEqual(acwi["source"], "ACWI official")
        self.assertEqual(acwi["observation_date"], "2026-09-23")
        self.assertEqual(acwi["value"], 160.22)
        self.assertEqual(acwi["previous_observation_date"], "2026-09-22")
        self.assertEqual(acwi["previous_value"], 162.20)
        self.assertEqual(acwi["delta"], {"value": -1.220715, "unit": "pct"})
        self.assertEqual(manifest["markets"]["UST_2Y"]["delta"], {"value": 14.0, "unit": "bp"})

    def test_stale_sources_do_not_move_calendar_anchor_backwards(self):
        raw = september_24_raw()
        for item in raw["series"].values():
            item["primary"] = source(("2026-09-21", 100.0), ("2026-09-22", 101.0))
            item.pop("fallback", None)
        manifest = validate.build_manifest(raw)
        self.assertEqual(manifest["expected_close_date"], "2026-09-23")
        self.assertEqual(manifest["data_quality"]["status"], "PASS_DEGRADED")
        for item in manifest["markets"].values():
            self.assertEqual(item["source_status"], "stale_last_good")
            self.assertEqual(item["observation_date"], "2026-09-22")

    def test_future_only_sources_are_unavailable(self):
        item = {
            "primary_name": "official",
            "primary": source(("2026-09-24", 159.59)),
            "fallback_name": "fallback",
            "fallback": source(("2026-09-25", 158.0)),
        }
        tier, _, history = validate.pick(item, "2026-09-23")
        self.assertEqual(tier, "unavailable")
        self.assertEqual(history, [])

    def test_future_rows_are_removed_from_both_sources_before_selection(self):
        item = {
            "primary_name": "official",
            "primary": source(("2026-09-22", 162.20), ("2026-09-24", 159.59)),
            "fallback_name": "fallback",
            "fallback": source(
                ("2026-09-22", 162.20), ("2026-09-23", 160.22), ("2026-09-25", 158.0)
            ),
        }
        tier, name, history = validate.pick(item, "2026-09-23")
        self.assertEqual((tier, name), ("fallback", "fallback"))
        self.assertEqual([row["date"] for row in history], ["2026-09-22", "2026-09-23"])

    def test_stale_single_official_close_uses_strictly_earlier_fallback(self):
        item = {
            "primary_name": "official",
            "primary": source(("2026-09-22", 162.20)),
            "fallback_name": "fallback",
            "fallback": source(
                ("2026-09-21", 161.85),
                ("2026-09-22", 999.0),  # same day cannot be a previous observation
                ("2026-09-24", 159.59),
            ),
        }
        tier, name, history = validate.pick(item, "2026-09-23")
        self.assertEqual((tier, name), ("stale", "official"))
        self.assertEqual(history, [
            {"date": "2026-09-21", "value": 161.85},
            {"date": "2026-09-22", "value": 162.20},
        ])

    def test_duplicate_dates_cannot_create_same_day_delta(self):
        item = {
            "primary_name": "official",
            "primary": source(("2026-09-23", 160.22), ("2026-09-23", 160.22)),
            "fallback_name": "fallback",
            "fallback": source(("2026-09-22", 162.20), ("2026-09-23", 160.22)),
        }
        _, _, history = validate.pick(item, "2026-09-23")
        self.assertEqual([row["date"] for row in history], ["2026-09-22", "2026-09-23"])

    def test_retrieval_retains_32_unique_dates_for_later_cutoff_selection(self):
        start = date(2026, 8, 1)
        rows = [{"date": (start + timedelta(days=index)).isoformat(), "value": float(index)}
                for index in range(40)]
        # Out-of-order duplicate latest rows must not crowd out older history.
        inputs = list(reversed(rows)) + [rows[-1].copy()] * 5
        retained = retrieve.latest_history(iter(inputs))
        self.assertEqual(len(retained), 32)
        self.assertEqual([row["date"] for row in retained], [row["date"] for row in rows[-32:]])


class AcceptanceTemporalTests(unittest.TestCase):
    def setUp(self):
        self.manifest = validate.build_manifest(september_24_raw())

    def test_valid_manifest_passes_temporal_acceptance(self):
        acceptance.assert_temporal_contract(self.manifest)

    def test_original_intraday_manifest_fails_even_with_degraded_quality(self):
        old = deepcopy(self.manifest)
        old["expected_close_date"] = "2026-09-24"
        old["data_quality"]["status"] = "PASS_DEGRADED"
        for item in old["markets"].values():
            item["expected_date"] = "2026-09-24"
            item["source_status"] = "stale_last_good"
        old["markets"]["ACWI"].update({
            "source_status": "fallback_verified",
            "observation_date": "2026-09-24",
            "value": 159.59,
            "previous_observation_date": "2026-09-23",
            "previous_value": 160.22,
            "delta": {"value": -0.393209, "unit": "pct"},
        })
        with self.assertRaises(AssertionError):
            acceptance.assert_temporal_contract(old)

    def test_future_current_close_fails(self):
        self.manifest["markets"]["ACWI"]["observation_date"] = "2026-09-24"
        with self.assertRaises(AssertionError):
            acceptance.assert_temporal_contract(self.manifest)

    def test_previous_observation_must_be_strictly_earlier_than_current(self):
        for invalid_previous in ("2026-09-23", "2026-09-24"):
            with self.subTest(previous=invalid_previous):
                manifest = deepcopy(self.manifest)
                manifest["markets"]["ACWI"]["previous_observation_date"] = invalid_previous
                with self.assertRaises(AssertionError):
                    acceptance.assert_temporal_contract(manifest)

    def test_incorrect_delta_fails(self):
        self.manifest["markets"]["ACWI"]["delta"]["value"] = -0.393209
        with self.assertRaises(AssertionError):
            acceptance.assert_temporal_contract(self.manifest)

    def test_incorrect_delta_unit_fails(self):
        self.manifest["markets"]["UST_2Y"]["delta"]["unit"] = "pct"
        with self.assertRaises(AssertionError):
            acceptance.assert_temporal_contract(self.manifest)


if __name__ == "__main__":
    unittest.main()
