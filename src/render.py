from __future__ import annotations

import argparse
import html
import json
from datetime import date
from pathlib import Path

import cairosvg
import yaml

from geography import load_polygon, project, svg_path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

DEFAULT_FAMILY = "Noto Sans CJK JP,DejaVu Sans,Arial,sans-serif"


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def svg_text(x, y, value, size, weight=700, anchor="start", fill="#000") -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="{DEFAULT_FAMILY}" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" '
        f'fill="{fill}">{esc(value)}</text>'
    )


def format_market(name: str, item: dict) -> tuple[str, str, str | None]:
    if item["value"] is None:
        return "N/D", "", None

    value = float(item["value"])
    if name in {"UST_2Y", "UST_10Y", "REAL_10Y"}:
        shown = f"{value:.2f}%"
    elif name == "SP500":
        shown = f"{value:,.2f}"
    else:
        shown = f"{value:.2f}"

    delta = item.get("delta")
    if not delta:
        delta_shown = "N/D"
    elif delta["unit"] == "bp":
        bp = float(delta["value"])
        delta_shown = "0 bp" if abs(bp) < 0.5 else f"{bp:+.0f} bp"
    else:
        pct = float(delta["value"])
        pct = 0.0 if abs(pct) < 0.005 else pct
        delta_shown = f"{pct:+.2f}%"

    return shown, delta_shown, item.get("observation_date")


def wrap(text_value: str, max_chars: int, max_lines: int) -> list[str]:
    words = text_value.split()
    lines, current = [], ""
    for word in words:
        proposal = (current + " " + word).strip()
        if len(proposal) <= max_chars:
            current = proposal
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]


def education_block(edition_date: str, forced: str) -> tuple[str, list[str]]:
    if forced in {"japanese", "geography"}:
        kind = forced
    else:
        local_day = date.fromisoformat(edition_date)
        kind = "japanese" if local_day.toordinal() % 2 == 0 else "geography"

    if kind == "japanese":
        return "japanese", [
            "JAPONÉS · N5",
            "Traduce usando いちばん:",
            "Este libro es el más caro.",
            "Kono hon ga ichiban takai desu.",
            "この本がいちばん高いです。",
        ]
    return "geography", []


def project_point(lon: float, lat: float, viewport: list[float], x: float, y: float, width: float, height: float) -> tuple[float, float]:
    return project([(lon, lat)], viewport, x, y, width, height)[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--education-mode",
        choices=("auto", "japanese", "geography"),
        default="auto",
    )
    parser.add_argument("--output-prefix", default="latest")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validated = json.loads((OUT / "validated.json").read_text(encoding="utf-8"))
    layout = yaml.safe_load((ROOT / "config" / "layout.yaml").read_text(encoding="utf-8"))
    cities = yaml.safe_load((ROOT / "config" / "cities.yaml").read_text(encoding="utf-8"))
    typ = layout["typography"]

    labels = {
        "UST_2Y": "UST 2Y",
        "UST_10Y": "UST 10Y",
        "REAL_10Y": "REAL 10Y",
        "SP500": "S&P 500",
        "ACWI": "ACWI",
        "MONEX": "MONEX",
    }

    clip_right = float(layout["layout"]["narrative_clip_right"])
    clip_width = max(10.0, clip_right - 320.0)

    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480" viewBox="0 0 800 480">',
        '<rect width="800" height="480" fill="#fff"/>',
        f'<defs><clipPath id="narrativeClip"><rect x="320" y="318" width="{clip_width:.1f}" height="140"/></clipPath></defs>',
        '<line x1="500" y1="0" x2="500" y2="292" stroke="#000" stroke-width="2"/>',
        '<line x1="0" y1="292" x2="800" y2="292" stroke="#000" stroke-width="2.5"/>',
    ]

    row_y = [38, 82, 126, 170, 214, 258]
    for idx, (name, y) in enumerate(zip(labels, row_y)):
        item = validated["markets"][name]
        value, delta, obs_date = format_market(name, item)
        svg.append(svg_text(18, y, labels[name], typ["market_label"], 800))
        svg.append(svg_text(300, y, value, typ["market_value"], 800, "end"))
        svg.append(svg_text(322, y, delta, typ["market_delta"], 800))
        if obs_date and obs_date != validated["expected_close_date"] and len(obs_date) >= 10:
            svg.append(svg_text(486, y, obs_date[5:], 9, 700, "end", "#555"))
        if idx < 5:
            svg.append(
                f'<line x1="16" y1="{y+13}" x2="490" y2="{y+13}" '
                'stroke="#777" stroke-width=".8"/>'
            )

    svg += [
        svg_text(516, 34, validated["edition_date"], 21, 800),
        '<line x1="514" y1="46" x2="786" y2="46" stroke="#000" stroke-width="1.5"/>',
        svg_text(516, 72, "LECTURA", typ["reading_heading"], 800),
        svg_text(516, 96, "Hechos", 13, 800),
    ]

    for i, line in enumerate(validated["reading"]["facts"]):
        svg.append(svg_text(520, 118 + i * 22, "• " + line, typ["reading_body"], 650))

    svg.append(svg_text(516, 192, "Interpretación", 13, 800))
    for i, line in enumerate(validated["reading"]["interpretation"]):
        for j, wrapped in enumerate(wrap(line, 38, 2)):
            prefix = "• " if j == 0 else "  "
            svg.append(
                svg_text(
                    520,
                    214 + (i * 38) + j * 18,
                    prefix + wrapped,
                    typ["reading_body"],
                    650,
                )
            )

    kind, block = education_block(validated["edition_date"], args.education_mode)
    if kind == "japanese":
        svg += [
            svg_text(18, 326, block[0], typ["education_heading"], 800),
            svg_text(18, 355, block[1], typ["education_body"], 700),
            svg_text(18, 401, block[2], 29, 800),
            svg_text(18, 444, block[3], typ["japanese_answer"], 650, fill="#777"),
            svg_text(18, 464, block[4], typ["japanese_answer"] + 1, 650, fill="#777"),
        ]
    else:
        city = cities["cities"][0]
        divider_x = float(layout["layout"]["map_divider_x"])
        svg.append(
            f'<line x1="{divider_x}" y1="306" x2="{divider_x}" y2="464" '
            'stroke="#000" stroke-width="1.5"/>'
        )
        svg += [
            svg_text(18, 326, city["city"].upper(), typ["education_heading"], 800),
            svg_text(18, 350, city["country"], 17, 800),
            svg_text(18, 381, city["population"], 15, 750),
            svg_text(18, 407, city["location"], 13, 650),
            svg_text(18, 431, city["physical_reference"], 13, 650),
        ]

        narrative = wrap(city["narrative"], 32, 4)
        svg.append('<g clip-path="url(#narrativeClip)">')
        for i, line in enumerate(narrative):
            svg.append(svg_text(320, 340 + i * 21, line, 13, 650))
        svg.append("</g>")

        map_x, map_y, map_w, map_h = divider_x + 10, 316, 210, 138
        viewport = city["viewport"]

        points = load_polygon(ROOT / city["map_asset"])
        mapped = project(points, viewport, map_x, map_y, map_w, map_h)
        svg.append(
            f'<path d="{svg_path(mapped)}" fill="#fafafa" stroke="#000" stroke-width="1.8"/>'
        )

        river = city.get("river")
        if river and river.get("points"):
            river_points = project(
                [(float(lon), float(lat)) for lon, lat in river["points"]],
                viewport,
                map_x,
                map_y,
                map_w,
                map_h,
            )
            river_d = " ".join(
                [f"M {river_points[0][0]:.1f} {river_points[0][1]:.1f}"]
                + [f"L {x:.1f} {y:.1f}" for x, y in river_points[1:]]
            )
            svg.append(
                f'<path d="{river_d}" fill="none" stroke="#777" stroke-width="1.15"/>'
            )
            rx, ry = project_point(
                float(river["label_lon"]),
                float(river["label_lat"]),
                viewport,
                map_x,
                map_y,
                map_w,
                map_h,
            )
            svg.append(svg_text(rx + 3, ry - 3, river["name"], 9, 650, fill="#666"))

        country_label = city.get("country_label")
        if country_label:
            lx, ly = project_point(
                float(country_label["lon"]),
                float(country_label["lat"]),
                viewport,
                map_x,
                map_y,
                map_w,
                map_h,
            )
            svg.append(svg_text(lx, ly, country_label["text"], 10, 750, "middle", "#555"))

        for label in city.get("labels", []):
            lx, ly = project_point(
                float(label["lon"]),
                float(label["lat"]),
                viewport,
                map_x,
                map_y,
                map_w,
                map_h,
            )
            svg.append(
                svg_text(
                    lx,
                    ly,
                    label["text"],
                    9,
                    650,
                    label.get("anchor", "start"),
                    "#666",
                )
            )

        cx, cy = project_point(
            float(city["lon"]),
            float(city["lat"]),
            viewport,
            map_x,
            map_y,
            map_w,
            map_h,
        )
        svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.2" fill="#000"/>')
        svg.append(svg_text(cx + 7, cy + 3, city["city"], 10, 800))

    svg += [
        '<line x1="0" y1="470" x2="800" y2="470" stroke="#000" stroke-width="1"/>',
        svg_text(12, 479, "Treasury | FRED | iShares/market | BCCR", typ["footer"], 700),
        svg_text(788, 479, f"Cierre {validated['expected_close_date']}", typ["footer"], 700, "end"),
        "</svg>",
    ]

    svg_output = "\n".join(svg)
    svg_path_out = OUT / f"{args.output_prefix}.svg"
    png_path_out = OUT / f"{args.output_prefix}.png"
    svg_path_out.write_text(svg_output, encoding="utf-8")
    cairosvg.svg2png(
        bytestring=svg_output.encode("utf-8"),
        write_to=str(png_path_out),
        output_width=800,
        output_height=480,
    )


if __name__ == "__main__":
    main()
