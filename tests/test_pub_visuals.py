from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent


def _load(script: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(script.stem + "_mod", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


diagram_mod = _load(REPO / "skills/pub-visuals/scripts/render_diagram.py")
cover_mod = _load(REPO / "skills/pub-visuals/scripts/gen_cover.py")

from scripts.lib import images, publication
from scripts.lib.config import Config

PNG_1X1 = bytes.fromhex("89504e470d0a1a0a0000000d494844520000060000000384080600000000" + "00" * 8)


def _repo(tmp_path: Path, **env):
    (tmp_path / ".seo-engine").mkdir()
    root = tmp_path / "publications" / "pl"
    (root / "drafts").mkdir(parents=True)
    (root / "site.yml").write_text(yaml.safe_dump({"name": "Prompt Ledger", "slug": "pl", "tagline": "t", "site_url": "https://pl.example",
                                                  "theme": "signal", "sections": [{"slug": "features", "name": "Features"}], "authors": []}))
    publication.write_post(root / "drafts" / "piece.md", {"title": "AI Search Ad Spend Doubles", "slug": "piece", "dek": "A dek.",
        'visual_plan': {'cover': {'kind': 'generated', 'subject': 'A branching path towards an advertising display',
                                  'purpose': 'Illustrate the choice of advertising channels', 'aspect_ratio': '16:9'}}}, "body")
    return Config(repo_root=tmp_path, env=dict(env), site={"publications_dir": "publications"}), root


def _run(mod, cfg, argv, monkeypatch, capsys):
    monkeypatch.setattr(mod.config_module, "load", lambda *a, **k: cfg)
    monkeypatch.setattr(sys, "argv", ["x", *argv])
    code = mod.main()
    out = json.loads(capsys.readouterr().out)
    out["_exit"] = code
    return out


def test_render_all_diagram_types(tmp_path, monkeypatch, capsys):
    cfg, root = _repo(tmp_path)
    specs = {
        "diagram-1.json": {"type": "stat_callout", "title": "AI Search Ad Spend: From 1.3% to 13.6%", "source": "eMarketer, 2025",
                           "data": {"from": "1.3%", "to": "13.6%", "from_sub": "$2.08B", "to_sub": "$25.93B", "from_label": "2026", "to_label": "2029", "span_label": "3 years"}},
        "diagram-2.json": {"type": "stepped_flow", "title": "Four readiness dimensions", "data": {"steps": [{"label": "Measurement", "detail": "close the attribution gap first"}, {"label": "Creative"}, {"label": "Targeting"}, {"label": "Budget"}]}},
        "diagram-3.json": {"type": "funnel", "title": "Prompt types", "data": {"stages": [{"label": "Exploratory", "value": "62%"}, {"label": "Comparison", "value": "22%"}, {"label": "Purchase", "value": "16%"}]}},
        "diagram-4.json": {"type": "comparison", "title": "CPM by surface", "data": {"items": [{"label": "ChatGPT", "value": "$60"}, {"label": "Search", "value": "$25"}]}},
        "diagram-5.json": {"type": "timeline", "title": "Ad launches", "data": {"points": [{"date": "Feb 2026", "label": "ChatGPT ads"}, {"date": "Sep 2026", "label": "Pilot results"}]}},
    }
    (root / "assets" / "piece").mkdir(parents=True)
    for name, spec in specs.items():
        (root / "assets" / "piece" / name).write_text(json.dumps(spec))
    out = _run(diagram_mod, cfg, ["--publication", "pl", "--slug", "piece", "--png"], monkeypatch, capsys)
    assert out["_exit"] == 0 and len(out["rendered"]) == 5
    svg1 = (root / "assets" / "piece" / "diagram-1.svg").read_text()
    assert 'viewBox="0 0 2910 1350"' in svg1 and "13.6%" in svg1 and "Source: eMarketer, 2025" in svg1 and "#00e5b4" in svg1
    assert "AI SEARCH AD SPEND" in svg1
    assert "Measurement" in (root / "assets" / "piece" / "diagram-2.svg").read_text()
    assert publication.image_dimensions(root / "assets" / "piece" / "diagram-3.svg") == (2910, 1350)
    assert all("png_note" in r for r in out["rendered"])


def test_cover_svg_fallback_and_providers(tmp_path, monkeypatch, capsys, fake_transport):
    cfg, root = _repo(tmp_path)
    blocked = _run(cover_mod, cfg, ["--publication", "pl", "--slug", "piece"], monkeypatch, capsys)
    assert blocked['_exit'] == 1 and 'OPENROUTER_API_KEY' in blocked['error']
    out = _run(cover_mod, cfg, ["--publication", "pl", "--slug", "piece", '--provider', 'svg'], monkeypatch, capsys)
    assert out["_exit"] == 0 and out["cover"]["generator"] == "svg-fallback"
    meta, _ = publication.read_post(root / "drafts" / "piece.md")
    assert meta["cover"]["alt"] == '' and meta['cover']['decorative'] and meta["cover"]["width"] == 1600
    assert meta['image_assets']['cover.svg']['mime'] == 'image/svg+xml' and out['requires_visual_review']
    assert (root / "assets" / "piece" / "cover.svg").read_text().startswith("<svg")
    skipped = _run(cover_mod, cfg, ["--publication", "pl", "--slug", "piece"], monkeypatch, capsys)
    assert skipped["skipped"] is True

    cfg2 = Config(repo_root=tmp_path, env={"OPENROUTER_API_KEY": "sk"}, site={"publications_dir": "publications"})
    fake_transport.route("POST", "https://openrouter.ai/api/v1/images",
                         {"body": json.dumps({"data": [{"b64_json": base64.b64encode(PNG_1X1).decode()}]})})
    out2 = _run(cover_mod, cfg2, ["--publication", "pl", "--slug", "piece", "--force"], monkeypatch, capsys)
    assert out2["cover"]["generator"].startswith("openrouter/") and out2["cover"]["width"] == 1536 and out2["cover"]["src"] == "cover.png"
    body = fake_transport.calls[-1][2]["json"]
    assert body["aspect_ratio"] == "16:9" and "A branching path" in body["prompt"] and "#ff4d1c" in body["prompt"]
    meta, _ = publication.read_post(root / 'drafts/piece.md')
    assert 'alt' not in meta['cover']  # The host must inspect before describing generated pixels.
    assert meta['image_assets']['cover.png']['source_type'] == 'generated'

    gen = images.generate_image(cfg2, "x", model="openai/gpt-image-1", aspect_ratio="1:1")
    assert gen["provider"] == "openrouter" and gen["mime"] == "image/png" and gen["bytes"] == PNG_1X1
    assert fake_transport.calls[-1][2]["json"]["model"] == "openai/gpt-image-1"
    assert fake_transport.calls[-1][2]["json"]["aspect_ratio"] == "1:1"
    with pytest.raises(images.ImageError):
        images.generate_image(Config(repo_root=tmp_path, env={}, site={}), "x")


def test_cover_honors_selected_model_and_does_not_generate_factual_assets(tmp_path, monkeypatch, capsys, fake_transport):
    cfg, root = _repo(tmp_path, OPENROUTER_API_KEY='key', IMAGE_MODEL='openai/gpt-image-1')
    fake_transport.route('POST', 'https://openrouter.ai/api/v1/images', {'body': json.dumps({
        'data': [{'b64_json': base64.b64encode(PNG_1X1).decode(), 'media_type': 'image/png'}]})})
    out = _run(cover_mod, cfg, ['--publication', 'pl', '--slug', 'piece'], monkeypatch, capsys)
    assert out['cover']['generator'] == 'openrouter/openai/gpt-image-1'
    assert len(fake_transport.calls) == 1 and 'openrouter.ai' in fake_transport.calls[0][1]
    meta, body = publication.read_post(root / 'drafts/piece.md')
    meta['visual_plan']['cover']['kind'] = 'screenshot'
    publication.write_post(root / 'drafts/piece.md', meta, body)
    refused = _run(cover_mod, cfg, ['--publication', 'pl', '--slug', 'piece', '--force'], monkeypatch, capsys)
    assert refused['_exit'] == 1 and len(fake_transport.calls) == 1
    with pytest.raises(images.ImageError, match='OPENROUTER_API_KEY'):
        images.pick_image_provider(Config(repo_root=tmp_path, env={'OPENAI_API_KEY': 'x', 'IMAGE_PROVIDER': 'gemini'}))


@pytest.mark.parametrize('data', [[], [{'b64_json': 'broken base64'}],
                                  [{'b64_json': base64.b64encode(b'not an image').decode()}]])
def test_image_gateway_rejects_missing_or_invalid_bytes(tmp_path, fake_transport, data):
    cfg = Config(repo_root=tmp_path, env={'OPENROUTER_API_KEY': 'key'}, site={})
    fake_transport.route('POST', 'https://openrouter.ai/api/v1/images', {'body': json.dumps({'data': data})})
    with pytest.raises(images.ImageError):
        images.generate_image(cfg, 'illustration')
