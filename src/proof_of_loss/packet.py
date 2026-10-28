"""Render the claim packet: one self-contained, printable HTML page."""

import base64
import html
from datetime import datetime

from . import config, evidence, vision
from .store import BlobStore

VERDICT_TEXT = {
    "supported": "Weather record supports the reported cause",
    "inconclusive": "Weather record neither confirms nor rules out the reported cause",
    "contradicted": "Weather record does not show the reported cause - field inspection requested",
}

CSS = """
body{font-family:system-ui,-apple-system,"Noto Sans","Noto Sans Devanagari",sans-serif;
 color:#1d1d1b;background:#fff;max-width:820px;margin:24px auto;padding:0 16px;line-height:1.45}
h1{font-size:1.5rem;margin:0}h2{font-size:1.05rem;margin:28px 0 8px;border-bottom:1px solid #ccc;padding-bottom:4px}
.hi{color:#555;font-weight:400}table{border-collapse:collapse;width:100%;font-size:.92rem}
td,th{border:1px solid #ccc;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f3f1ec;width:34%}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-weight:600}
.supported{background:#dcefd9}.inconclusive{background:#f6ecc9}.contradicted{background:#f6d6d0}
.photos{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.photos img{width:100%;border:1px solid #ccc}.small{font-size:.82rem;color:#555}
@media print{body{margin:0}}
"""


def _e(value) -> str:
    return html.escape(str(value)) if value not in (None, "") else "-"


def _rows(pairs) -> str:
    return "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in pairs)


def render(claim: dict, blobs: BlobStore, now: datetime) -> str:
    f, loss, w = claim["farmer"], claim["loss"], claim["weather"]
    dl = evidence.deadline_info(loss["loss_date"], loss["time_of_day"], now)

    photo_cards = []
    for pid, p in claim["photos"].items():
        if not p.get("inspected"):
            continue
        img = base64.b64encode(vision.shrink(blobs.read(p["key"]), 640)).decode()
        loc = p.get("location")
        loc_txt = f"{loc['lat']:.5f}, {loc['lon']:.5f} ({loc['source']})" if loc else "no location"
        flags = "; ".join(p.get("flags") or []) or "none"
        seen = (p.get("vision") or {}).get("visible_damage", "-")
        photo_cards.append(
            f"<figure><img alt='Photo {_e(pid)}' src='data:image/jpeg;base64,{img}'>"
            f"<figcaption class='small'><b>{_e(pid)}</b> taken {_e(p.get('taken_at'))} "
            f"({_e(p.get('time_source'))})<br>Location: {_e(loc_txt)}<br>Flags: {_e(flags)}"
            f"<br>Visible (AI note, not a judgement): {_e(seen)}</figcaption></figure>")

    weather_rows = "".join(
        f"<tr><td>{_e(d['date'])}</td><td>{d['precip_mm']:.1f}</td><td>{_e(d['weather_code'])}</td>"
        f"<td>{_e(d['max_gust_kmh'])}</td></tr>" for d in w["days"])

    confirm = ""
    if w["verdict"] == "contradicted":
        confirm = ("<p><b>Farmer confirmation:</b> the farmer was shown that the weather record does "
                   "not match and chose to file anyway. Weather grids are about 10 km wide and can "
                   "miss a local storm, so a field inspection is requested.</p>")

    audit = "".join(
        f"<tr><td>{_e(a['at'])}</td><td>{_e(a['tool'])}</td><td>{_e(a['status'])}</td></tr>"
        for a in claim["audit"])

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Crop loss claim {_e(claim['claim_id'])}</title><style>{CSS}</style></head><body>
<h1>Crop loss intimation packet <span class="hi">/ फसल नुकसान सूचना</span></h1>
<p class="small">Claim {_e(claim['claim_id'])} &middot; prepared {now.strftime('%d %b %Y, %H:%M')} IST
under PMFBY localized calamity rules (report within {config.REPORT_WINDOW_HOURS} hours).</p>

<h2>Farmer <span class="hi">/ किसान</span></h2>
<table>{_rows([("Name", _e(f.get('name'))), ("Village", _e(f.get('village'))),
               ("District", _e(f.get('district'))), ("State", _e(f.get('state')))])}</table>

<h2>Loss <span class="hi">/ नुकसान</span></h2>
<table>{_rows([("Crop", _e(loss.get('crop'))), ("Cause", _e(loss.get('peril'))),
               ("Area affected", f"{_e(loss.get('area_acres'))} acres"),
               ("Date of loss", f"{_e(loss.get('loss_date'))} ({_e(loss.get('time_of_day'))})"),
               ("Description", _e(loss.get('description'))),
               ("Report by", f"{_e(dl['report_by'])} ({dl['hours_left']} hours left at preparation)")])}</table>

<h2>Weather check <span class="hi">/ मौसम जाँच</span></h2>
<p><span class="tag {w['verdict']}">{VERDICT_TEXT[w['verdict']]}</span></p>
<p>{_e(w['reason'])}</p>
<table><tr><th>Date</th><th>Rain (mm)</th><th>WMO code</th><th>Max gust (km/h)</th></tr>{weather_rows}</table>
<p class="small">Source: {_e(w['source'])}, grid point {w['grid_lat']:.3f}, {w['grid_lon']:.3f}
(photo at {w['lat']:.4f}, {w['lon']:.4f}). WMO codes 95-99 mean thunderstorm.</p>
{confirm}

<h2>Photo evidence <span class="hi">/ फोटो</span></h2>
<div class="photos">{''.join(photo_cards)}</div>

<h2>How to submit <span class="hi">/ कैसे जमा करें</span></h2>
<ol>{''.join(f'<li>{_e(c)}</li>' for c in config.PMFBY_CHANNELS)}</ol>

<h2>How this packet was made</h2>
<p class="small">Prepared by Proof of Loss, an AI assistant. It collects and checks evidence; it does
not decide the claim. The insurer and the state loss-assessment committee decide.</p>
<table><tr><th>Time</th><th>Step</th><th>Result</th></tr>{audit}</table>
</body></html>"""
