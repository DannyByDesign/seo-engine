"""pub-visuals: render the house-style diagrams the measured phantoms carry
(publication-playbook §3): 2910x1350, small-caps kicker title top-left, one
big idea (a stat callout, a stepped flow, a funnel, a comparison, a timeline),
a `Source:` footer, theme colours — deterministic SVG from a JSON spec, no
image model, no API key. PNG is produced too when `cairosvg` (pip) or
`rsvg-convert` (librsvg) is available; otherwise the SVG is the asset, which
every browser and crawler renders.

Spec (written by pub-enhance's `diagrams` stage into assets/<slug>/diagram-N.json):
  {"type": "stat_callout" | "stepped_flow" | "funnel" | "comparison" | "timeline",
   "title": "AI Search Ad Spend: From 1.3% to 13.6% in Three Years",
   "brief": "Show the share trajectory ...",
   "data": {...},              # shape per type, see _render_* below
   "source": "eMarketer, 2025", "alt": "Diagram: ... Visualizes: ..."}

Usage:
    python3 render_diagram.py --publication llm-billboard --slug advertiser-readiness           # every spec for the article
    python3 render_diagram.py --publication llm-billboard --spec publications/llm-billboard/assets/x/diagram-1.json --png
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info < (3, 9):
    sys.exit("seo-engine requires Python 3.9+ (found %d.%d)" % sys.version_info[:2])


def _find_engine_root(start: Path) -> Path:
    import os

    env = os.environ.get("SEO_ENGINE_ROOT")
    if env and (Path(env) / "scripts" / "lib" / "config.py").is_file():
        return Path(env)
    for candidate in [start, *start.parents]:
        if (candidate / "scripts" / "lib" / "config.py").is_file():
            return candidate
    raise SystemExit(
        "Could not locate seo-engine root (scripts/lib/config.py). If skills were "
        "copied (not symlinked), set SEO_ENGINE_ROOT=/path/to/seo-engine."
    )


sys.path.insert(0, str(_find_engine_root(Path(__file__).resolve())))
from scripts.lib import config as config_module  # noqa: E402

import argparse  # noqa: E402
import html  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
from typing import Any  # noqa: E402

from scripts.lib import publication  # noqa: E402

W, H = 2910, 1350
PAD = 150


def _e(s: Any) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _num(v: Any) -> float:
    try:
        return float(str(v).replace("$", "").replace(",", "").replace("%", "").split()[0])
    except (ValueError, IndexError):
        return 0.0


def _frame(theme: dict[str, Any], title: str, source: str, body: str) -> str:
    font_h = theme.get("font_heading", "Inter, system-ui, sans-serif")
    font_b = theme.get("font_body", "Inter, system-ui, sans-serif")
    font_m = theme.get("font_mono", "ui-monospace, monospace")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{_e(title)}">'
        f'<rect width="{W}" height="{H}" fill="{theme.get("surface", "#f0ede8")}"/>'
        f'<text x="{PAD}" y="{PAD + 10}" font-family="{_e(font_m)}" font-size="34" letter-spacing="6" fill="{theme.get("fg", "#1a1a1a")}" '
        f'style="text-transform:uppercase">{_e(title.upper())}</text>'
        f'<g font-family="{_e(font_b)}">{body}</g>'
        f'<text x="{PAD}" y="{H - PAD + 40}" font-family="{_e(font_h)}" font-size="30" fill="{theme.get("muted", "#666")}">Source: {_e(source)}</text>'
        "</svg>\n"
    )


def _render_stat_callout(theme: dict[str, Any], data: dict[str, Any]) -> str:
    """{from, to, from_label, to_label, from_sub, to_sub, span_label} or {value, label}."""
    primary, accent, fg, muted = theme.get("primary", "#111"), theme.get("accent", "#0ea5e9"), theme.get("fg", "#1a1a1a"), theme.get("muted", "#666")
    if "to" not in data:
        return (f'<text x="{W / 2}" y="{H / 2 + 60}" text-anchor="middle" font-size="260" font-weight="700" fill="{accent}">{_e(data.get("value", ""))}</text>'
                f'<text x="{W / 2}" y="{H / 2 + 170}" text-anchor="middle" font-size="48" fill="{muted}">{_e(data.get("label", ""))}</text>')
    x0, x1, base, top = 620, 2280, 1060, 340
    left = (f'<text x="380" y="720" text-anchor="middle" font-size="150" font-weight="700" fill="{fg}">{_e(data.get("from"))}</text>'
            f'<text x="380" y="800" text-anchor="middle" font-size="46" fill="{muted}">{_e(data.get("from_sub", ""))}</text>'
            f'<line x1="380" y1="870" x2="380" y2="960" stroke="{muted}" stroke-width="3"/>'
            f'<text x="380" y="1040" text-anchor="middle" font-size="44" fill="{muted}">{_e(data.get("from_label", ""))}</text>')
    right = (f'<text x="2520" y="720" text-anchor="middle" font-size="150" font-weight="700" fill="{accent}">{_e(data.get("to"))}</text>'
             f'<text x="2520" y="800" text-anchor="middle" font-size="46" fill="{muted}">{_e(data.get("to_sub", ""))}</text>'
             f'<line x1="2520" y1="870" x2="2520" y2="960" stroke="{accent}" stroke-width="3"/>'
             f'<text x="2520" y="1040" text-anchor="middle" font-size="44" fill="{muted}">{_e(data.get("to_label", ""))}</text>')
    area = (f'<defs><linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="{muted}" stop-opacity="0.15"/><stop offset="1" stop-color="{accent}" stop-opacity="0.55"/></linearGradient></defs>'
            f'<polygon points="{x0},{base} {x1},{top} {x1},{base}" fill="url(#g)"/>'
            f'<line x1="{x0}" y1="{base}" x2="{x1}" y2="{top}" stroke="{fg}" stroke-width="10"/>'
            f'<circle cx="{x0}" cy="{base}" r="18" fill="{fg}"/><circle cx="{x1}" cy="{top}" r="18" fill="{accent}"/>'
            f'<line x1="{x0}" y1="{base + 40}" x2="{x1}" y2="{base + 40}" stroke="{muted}" stroke-width="3" stroke-dasharray="12 12"/>'
            f'<text x="{(x0 + x1) / 2}" y="{base + 30}" text-anchor="middle" font-size="40" fill="{muted}">{_e(data.get("span_label", ""))}</text>')
    return left + right + area


def _render_stepped_flow(theme: dict[str, Any], data: dict[str, Any]) -> str:
    steps = [s if isinstance(s, dict) else {"label": str(s)} for s in data.get("steps", [])][:6] or [{"label": "—"}]
    primary, fg, muted, bg = theme.get("primary", "#111"), theme.get("fg", "#1a1a1a"), theme.get("muted", "#666"), theme.get("bg", "#fff")
    n = len(steps)
    gap = 60
    box_w = (W - 2 * PAD - gap * (n - 1)) / n
    box_h = 520
    y = 400
    parts = []
    for i, s in enumerate(steps):
        x = PAD + i * (box_w + gap)
        parts.append(f'<rect x="{x:.0f}" y="{y}" width="{box_w:.0f}" height="{box_h}" rx="18" fill="{bg}" stroke="{primary}" stroke-width="6"/>')
        parts.append(f'<text x="{x + 40:.0f}" y="{y + 90}" font-size="54" font-weight="700" fill="{primary}">{i + 1:02d}</text>')
        parts.append(f'<text x="{x + 40:.0f}" y="{y + 190}" font-size="48" font-weight="700" fill="{fg}">{_e(str(s.get("label", ""))[:34])}</text>')
        detail = str(s.get("detail") or "")
        if detail:
            words, lines, cur = detail.split(), [], ""
            for w in words:
                if len(cur) + len(w) + 1 > 30:
                    lines.append(cur)
                    cur = w
                else:
                    cur = (cur + " " + w).strip()
            lines.append(cur)
            for k, line in enumerate(lines[:5]):
                parts.append(f'<text x="{x + 40:.0f}" y="{y + 270 + k * 52}" font-size="38" fill="{muted}">{_e(line)}</text>')
        if i < n - 1:
            ax = x + box_w + gap / 2
            parts.append(f'<path d="M{ax - 22:.0f},{y + box_h / 2 - 22} L{ax + 14:.0f},{y + box_h / 2} L{ax - 22:.0f},{y + box_h / 2 + 22} Z" fill="{muted}"/>')
    return "".join(parts)


def _render_funnel(theme: dict[str, Any], data: dict[str, Any]) -> str:
    stages = [s if isinstance(s, dict) else {"label": str(s)} for s in data.get("stages", [])][:6] or [{"label": "—"}]
    primary, accent, fg, muted = theme.get("primary", "#111"), theme.get("accent", "#0ea5e9"), theme.get("fg", "#1a1a1a"), theme.get("muted", "#666")
    n = len(stages)
    row_h = min(150, (H - 2 * PAD - 200) / n)
    max_w = W - 2 * PAD - 700
    parts = []
    for i, s in enumerate(stages):
        width = max_w * (1 - i * (0.7 / max(n - 1, 1)))
        x = PAD + 600 + (max_w - width) / 2
        y = 330 + i * (row_h + 24)
        color = accent if i == n - 1 else primary
        opacity = 0.35 + 0.65 * (i + 1) / n
        parts.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{width:.0f}" height="{row_h:.0f}" rx="12" fill="{color}" fill-opacity="{opacity:.2f}"/>')
        parts.append(f'<text x="{PAD}" y="{y + row_h / 2 + 16:.0f}" font-size="44" font-weight="700" fill="{fg}">{_e(str(s.get("label", ""))[:36])}</text>')
        if s.get("value") not in (None, ""):
            parts.append(f'<text x="{x + width / 2:.0f}" y="{y + row_h / 2 + 18:.0f}" text-anchor="middle" font-size="50" font-weight="700" fill="#fff">{_e(s["value"])}</text>')
    return "".join(parts)


def _render_comparison(theme: dict[str, Any], data: dict[str, Any]) -> str:
    items = [i if isinstance(i, dict) else {"label": str(i)} for i in data.get("items", [])][:6] or [{"label": "—", "value": 0}]
    primary, accent, fg, muted = theme.get("primary", "#111"), theme.get("accent", "#0ea5e9"), theme.get("fg", "#1a1a1a"), theme.get("muted", "#666")
    values = [_num(i.get("value")) for i in items]
    top = max(values) or 1.0
    n = len(items)
    row_h = min(140, (H - 2 * PAD - 200) / n)
    bar_max = W - 2 * PAD - 1000
    parts = []
    for i, (item, v) in enumerate(zip(items, values)):
        y = 330 + i * (row_h + 30)
        width = max(12.0, bar_max * v / top)
        color = accent if v == top else primary
        parts.append(f'<text x="{PAD}" y="{y + row_h / 2 + 16:.0f}" font-size="44" font-weight="700" fill="{fg}">{_e(str(item.get("label", ""))[:34])}</text>')
        parts.append(f'<rect x="{PAD + 800}" y="{y:.0f}" width="{width:.0f}" height="{row_h:.0f}" rx="10" fill="{color}"/>')
        parts.append(f'<text x="{PAD + 800 + width + 30:.0f}" y="{y + row_h / 2 + 18:.0f}" font-size="46" font-weight="700" fill="{fg}">{_e(item.get("value", ""))}{_e(item.get("unit", ""))}</text>')
    return "".join(parts)


def _render_timeline(theme: dict[str, Any], data: dict[str, Any]) -> str:
    points = [p if isinstance(p, dict) else {"label": str(p)} for p in data.get("points", [])][:7] or [{"label": "—"}]
    primary, accent, fg, muted = theme.get("primary", "#111"), theme.get("accent", "#0ea5e9"), theme.get("fg", "#1a1a1a"), theme.get("muted", "#666")
    n = len(points)
    y = 720
    x0, x1 = PAD + 100, W - PAD - 100
    parts = [f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{muted}" stroke-width="6"/>']
    for i, p in enumerate(points):
        x = x0 + (x1 - x0) * (i / max(n - 1, 1))
        parts.append(f'<circle cx="{x:.0f}" cy="{y}" r="22" fill="{accent if i == n - 1 else primary}"/>')
        parts.append(f'<text x="{x:.0f}" y="{y - 60}" text-anchor="middle" font-size="46" font-weight="700" fill="{fg}">{_e(p.get("date", ""))}</text>')
        parts.append(f'<text x="{x:.0f}" y="{y + 90}" text-anchor="middle" font-size="40" fill="{muted}">{_e(str(p.get("label", ""))[:28])}</text>')
    return "".join(parts)


RENDERERS = {"stat_callout": _render_stat_callout, "stepped_flow": _render_stepped_flow, "funnel": _render_funnel,
             "comparison": _render_comparison, "timeline": _render_timeline}


def render_svg(spec: dict[str, Any], theme: dict[str, Any]) -> str:
    kind = spec.get("type") if spec.get("type") in RENDERERS else "stat_callout"
    body = RENDERERS[kind](theme, spec.get("data") or {})
    return _frame(theme, str(spec.get("title") or ""), str(spec.get("source") or ""), body)


def to_png(svg_path: Path) -> tuple[Path | None, str]:
    png_path = svg_path.with_suffix(".png")
    try:
        import cairosvg  # type: ignore

        cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), output_width=W, output_height=H)
        return png_path, "cairosvg"
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        return None, f"cairosvg failed: {exc}"
    rsvg = shutil.which("rsvg-convert")
    if rsvg:
        subprocess.run([rsvg, "-w", str(W), "-h", str(H), "-o", str(png_path), str(svg_path)], check=False, capture_output=True)
        if png_path.is_file():
            return png_path, "rsvg-convert"
    return None, "no PNG converter (pip install cairosvg, or install librsvg) — SVG is the asset"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render house-style diagrams from JSON specs.")
    parser.add_argument("--publication", help="Publication slug")
    parser.add_argument("--slug", help="Article slug: render every assets/<slug>/diagram-*.json")
    parser.add_argument("--spec", action="append", default=[], help="Explicit spec path (repeatable)")
    parser.add_argument("--png", action="store_true", help="Also produce PNG when a converter is available")
    parser.add_argument("--publications-dir", help="Override the publications directory")
    args = parser.parse_args()

    cfg = config_module.load()
    if args.publications_dir:
        cfg.site["publications_dir"] = args.publications_dir
    root = publication.find_publication(cfg, args.publication)
    pub = publication.load_publication(root)
    specs = [Path(p) for p in args.spec]
    if args.slug:
        specs += sorted((root / "assets" / args.slug).glob("diagram-*.json"))
    if not specs:
        parser.error("pass --slug or --spec")
    outputs = []
    for spec_path in specs:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        if not spec.get("source"):
            spec["source"] = str((pub.site.get("client") or {}).get("name") or "").strip() and "" or ""
        svg = render_svg(spec, pub.theme)
        svg_path = spec_path.with_suffix(".svg")
        svg_path.write_text(svg, encoding="utf-8")
        entry: dict[str, Any] = {"spec": str(spec_path), "svg": str(svg_path), "type": spec.get("type", "stat_callout"), "width": W, "height": H}
        if args.png:
            png, note = to_png(svg_path)
            entry["png"] = str(png) if png else None
            entry["png_note"] = note
        outputs.append(entry)
    print(json.dumps({"checked": True, "publication": root.name, "rendered": outputs}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
