from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "reterminal-daily/0.1 (+https://github.com/humbertogrant/reterminal-daily)"
}


def get_text(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def parse_date(value: str) -> str | None:
    value = " ".join(value.split())
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def number(value: str) -> float | None:
    cleaned = value.replace("$", "").replace(",", "").replace("%", "").strip()
    if cleaned in {"", ".", "N/A", "NA", "-"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def latest_two(rows: Iterable[dict]) -> list[dict]:
    clean = [r for r in rows if r.get("date") and r.get("value") is not None]
    clean.sort(key=lambda x: x["date"])
    return clean[-2:]


def fred(url: str, series_id: str) -> list[dict]:
    text = get_text(url)
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        val = number(row.get(series_id, ""))
        obs_date = parse_date(row.get("DATE", ""))
        if obs_date and val is not None:
            rows.append({"date": obs_date, "value": val})
    return latest_two(rows)


def treasury(url: str, wanted: dict[str, str]) -> dict[str, list[dict]]:
    soup = BeautifulSoup(get_text(url), "html.parser")
    table = soup.find("table")
    if table is None:
        raise RuntimeError("Treasury table not found")

    header_cells = table.find("tr").find_all(["th", "td"])
    headers = [" ".join(c.get_text(" ", strip=True).split()) for c in header_cells]
    index = {name.lower(): i for i, name in enumerate(headers)}

    date_idx = next((i for i, h in enumerate(headers) if h.lower() == "date"), None)
    if date_idx is None:
        raise RuntimeError("Treasury Date column not found")

    positions: dict[str, int] = {}
    for series, column in wanted.items():
        key = column.lower()
        if key not in index:
            raise RuntimeError(f"Treasury column not found: {column}")
        positions[series] = index[key]

    found = {series: [] for series in wanted}
    for tr in table.find_all("tr")[1:]:
        cells = [" ".join(c.get_text(" ", strip=True).split()) for c in tr.find_all(["td", "th"])]
        if len(cells) <= date_idx:
            continue
        obs_date = parse_date(cells[date_idx])
        if not obs_date:
            continue
        for series, pos in positions.items():
            if pos < len(cells):
                val = number(cells[pos])
                if val is not None:
                    found[series].append({"date": obs_date, "value": val})

    return {series: latest_two(rows) for series, rows in found.items()}


def ishares_acwi(url: str) -> list[dict]:
    page_text = BeautifulSoup(get_text(url), "html.parser").get_text(" ", strip=True)
    match = re.search(
        r"Closing Price\s+\$?\s*([0-9][0-9,]*\.?[0-9]*)\s+as of\s+([A-Za-z]{3}\s+\d{1,2},\s+\d{4})",
        page_text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise RuntimeError("iShares Closing Price not found")
    obs_date = parse_date(match.group(2))
    value = number(match.group(1))
    if not obs_date or value is None:
        raise RuntimeError("iShares closing price could not be parsed")
    return [{"date": obs_date, "value": value}]


def stooq(url: str) -> list[dict]:
    text = get_text(url)
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        obs_date = parse_date(row.get("Date", ""))
        value = number(row.get("Close", ""))
        if obs_date and value is not None:
            rows.append({"date": obs_date, "value": value})
    return latest_two(rows)


def bccr_monex(url: str) -> list[dict]:
    soup = BeautifulSoup(get_text(url), "html.parser")
    for table in soup.find_all("table"):
        matrix = [
            [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            for tr in table.find_all("tr")
        ]
        if not any(cells and "weighted average" in " ".join(cells).lower() for cells in matrix):
            continue

        date_positions: dict[int, str] = {}
        for cells in matrix:
            for idx, cell in enumerate(cells):
                parsed = parse_date(cell)
                if parsed:
                    date_positions[idx] = parsed
            if len(date_positions) >= 2:
                break

        current_row = next(
            (
                cells
                for cells in matrix
                if cells
                and "weighted average" in cells[0].lower()
                and "previous session" not in cells[0].lower()
            ),
            None,
        )
        if current_row and date_positions:
            observations = []
            for idx, obs_date in date_positions.items():
                if idx < len(current_row):
                    val = number(current_row[idx])
                    if val is not None:
                        observations.append({"date": obs_date, "value": val})
            if observations:
                return latest_two(observations)

    raise RuntimeError("BCCR MONEX weighted-average row not found")


def safe(callable_, *args):
    try:
        return {"ok": True, "observations": callable_(*args)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "observations": []}


def main() -> None:
    config = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    year = datetime.now(timezone.utc).year

    nominal = safe(
        treasury,
        config["treasury_nominal"]["primary"]["url"].format(year=year),
        {"UST_2Y": "2 Yr", "UST_10Y": "10 Yr"},
    )
    real = safe(
        treasury,
        config["treasury_real"]["primary"]["url"].format(year=year),
        {"REAL_10Y": "10 Yr"},
    )

    raw = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "series": {
            "UST_2Y": {
                "primary_name": config["treasury_nominal"]["primary"]["name"],
                "primary": {
                    "ok": nominal["ok"],
                    "observations": nominal.get("observations", {}).get("UST_2Y", []) if nominal["ok"] else [],
                    "error": nominal.get("error"),
                },
                "fallback_name": "FRED DGS2",
                "fallback": safe(fred, config["treasury_nominal"]["fallback"]["UST_2Y"], "DGS2"),
            },
            "UST_10Y": {
                "primary_name": config["treasury_nominal"]["primary"]["name"],
                "primary": {
                    "ok": nominal["ok"],
                    "observations": nominal.get("observations", {}).get("UST_10Y", []) if nominal["ok"] else [],
                    "error": nominal.get("error"),
                },
                "fallback_name": "FRED DGS10",
                "fallback": safe(fred, config["treasury_nominal"]["fallback"]["UST_10Y"], "DGS10"),
            },
            "REAL_10Y": {
                "primary_name": config["treasury_real"]["primary"]["name"],
                "primary": {
                    "ok": real["ok"],
                    "observations": real.get("observations", {}).get("REAL_10Y", []) if real["ok"] else [],
                    "error": real.get("error"),
                },
                "fallback_name": "FRED DFII10",
                "fallback": safe(fred, config["treasury_real"]["fallback"]["REAL_10Y"], "DFII10"),
            },
            "SP500": {
                "primary_name": config["sp500"]["primary"]["name"],
                "primary": safe(fred, config["sp500"]["primary"]["url"], "SP500"),
            },
            "ACWI": {
                "primary_name": config["acwi"]["primary"]["name"],
                "primary": safe(ishares_acwi, config["acwi"]["primary"]["url"]),
                "fallback_name": config["acwi"]["fallback"]["name"],
                "fallback": safe(stooq, config["acwi"]["fallback"]["url"]),
            },
            "MONEX": {
                "primary_name": config["monex"]["primary"]["name"],
                "primary": safe(bccr_monex, config["monex"]["primary"]["url"]),
            },
        },
    }

    (OUT / "raw.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
