# reterminal-daily

Deterministic daily dashboard pipeline for a **reTerminal E1001 (800×480)**.

## Status

**Production spike v1.** The code is isolated on a feature branch and does **not** change E1001 firmware or publish to a public/static URL yet.

Risk: **R1 overall** because the eventual device integration will require a firmware/configuration change. The retrieval, validation and deterministic rendering path is R0.

## Architecture

```text
network retrieval
      ↓
output/raw.json
      ↓
validation + source hierarchy + recalculated deltas
      ↓
output/validated.json + latest_manifest.json
      ↓
render.py  ← NO NETWORK
      ↓
latest.svg
      ↓
latest.png (800×480)
      ↓
acceptance.py
```

The renderer never searches, fetches, fills, interpolates or invents market data.

## Source hierarchy

- **UST 2Y / UST 10Y:** U.S. Treasury Daily Treasury Par Yield Curve Rates → FRED DGS2/DGS10 fallback.
- **Real 10Y:** U.S. Treasury Daily Treasury Par Real Yield Curve Rates → FRED DFII10 fallback.
- **S&P 500:** FRED SP500.
- **ACWI:** iShares Closing Price → market-close fallback (Stooq in the spike).
- **MONEX:** BCCR weighted-average daily MONEX rate.

If an expected-date value is unavailable, validation keeps the latest verified observation and exposes its true date. If no verified observation is available in the current retrieval, the spike emits `N/D`; it never substitutes intraday data.

## Visual contract

- exact **800×480** output;
- SVG-first deterministic renderer;
- six fixed markets;
- `LECTURA` separated into facts and interpretation;
- educational rotation between **JLPT N5** and **GEOGRAFÍA**;
- large/heavy typography;
- shortening/wrapping before font shrinking;
- geography narrative has a hard SVG clip boundary before the map;
- local vector map asset: no map retrieval in the renderer.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install .
python src/retrieve.py
python src/validate.py
python src/render.py
python src/acceptance.py
```

Artifacts appear under `output/`.

## GitHub Actions

`.github/workflows/daily.yml` runs at **12:10 UTC = 06:10 Costa Rica**, plus manual `workflow_dispatch`.

For the spike it uploads an Actions artifact only. It does **not** yet publish `latest.png` to static hosting.

## Fail-closed behavior

The workflow stops on retrieval/parser/render/acceptance errors. A future publishing step must run only after acceptance passes, so a failed edition cannot replace the last known-good production image.

## Known gaps before production promotion

1. **Persistent last-known-good state across workflow runs.** The spike can use older observations returned by a source, but does not yet restore state from a previous Actions run when a source is completely unreachable.
2. **Static hosting.** Choose GitHub Pages, Cloudflare R2 or S3 after the pipeline soaks cleanly.
3. **Full city catalog.** The geography renderer is production-shaped, but the spike includes only Karachi plus a local Pakistan map fixture.
4. **MONEX parser soak.** The BCCR HTML is legacy/fragile; it needs several real daily runs before promotion.
5. **ACWI fallback review.** Stooq is acceptable for the spike but should be explicitly approved or replaced with the preferred production market-close fallback.

## Promotion gate

Run manually/daily for 3–5 editions and require:

- no invented values;
- correct observation dates and recalculated deltas;
- 800×480 every time;
- no text crossing the map divider;
- no typography regression;
- sensible weekend/holiday behavior.

Only then add static publication and ESPHome fetching of `latest.png`.

## Rollback

`main` remains untouched until the PR is reviewed and merged. Later production publication must be atomic: a failed run leaves the previous `latest.png` in place.
