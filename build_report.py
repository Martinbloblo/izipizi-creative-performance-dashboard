#!/usr/bin/env python3
"""
IZIPIZI Meta Ads - Creative Performance Dashboard builder.

Reads data_raw.csv (ad_name, cost, purchases, conv_value from Supermetrics
Facebook Ads, "Website purchases" attribution), parses the internal creative
nomenclature out of each ad_name, aggregates spend / ROAS / CPA per
nomenclature variable, and renders dashboard.html (Plotly.js, no build step).

Nomenclature (client-defined):
[DATE] - [FORMAT] - [CIBLE/PERSONA] - [GAMME] - [COLLECTION] - [COLORIS] -
[CONCEPT] - [PRIX] - [VERSION]

Ads whose name doesn't yield a recognizable value for a given variable are
excluded from that variable's chart only (per explicit user choice), but
still counted in the global totals.
"""
import csv
import json
import re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent
CSV_PATH = ROOT / "data_raw.csv"
OUT_PATH = ROOT / "dashboard.html"

# ---------------------------------------------------------------------------
# Nomenclature vocabularies
# ---------------------------------------------------------------------------

FORMAT_RULES = [
    ("video social friendly", "Video Social Friendly"),
    ("video ugc", "Video UGC"),
    ("ugc influence", "Video UGC"),
    ("video brand", "Video Brand"),
    ("image collection", "Image Collection"),
    ("carrousel dad", "Carrousel DAd"),
    ("carrousel", "Carrousel"),
    ("motion", "Motion"),
    ("gif", "Gif"),
    ("collection", "Image Collection"),
    ("image", "Image"),
    ("vidéo", "Video"),
    ("video", "Video"),
]

PERSONA_TOKENS = {
    "young dynamic": "Young Dynamic",
    "young presbyte": "Young Presbyte",
    "young parent": "Young Parent",
    "all targets": "All Targets",
    "all target": "All Targets",
}

GAMME_TOKENS = {
    "sun & kids": "SUN & KIDS",
    "sun/kids": "SUN & KIDS",
    "sun kids": "SUN & KIDS",
    "multi gamme": "MULTI GAMME",
    "multi": "MULTI GAMME",
    "sun": "SUN",
    "reading": "READING",
    "screen": "SCREEN",
    "sport": "SPORT",
    "kids": "KIDS",
    "sleeping": "SLEEPING",
}

COLLECTION_NAMED = {
    "crossroads", "permanent", "bonpoint", "alegria", "essential edition",
    "studio collection", "multi gamme", "best sellers", "all products",
    "holiday season",
}

COLORIS_RULES = [
    ("multi variantes", "Multi Variantes"),
    ("multi modèles", "Multi Variantes"),
    ("multi modeles", "Multi Variantes"),
    ("muli modèles", "Multi Variantes"),
    ("vintage cream", "Vintage Cream"),
    ("light tortoise", "Light Tortoise"),
    ("blue tortoise", "Blue Tortoise"),
    ("turquoise stone", "Turquoise Stone"),
    ("golden canyon", "Golden Canyon"),
    ("golden green", "Golden Green"),
    ("frozen blue", "Frozen Blue"),
    ("blue navy", "Blue Navy"),
    ("kaki green", "Kaki Green"),
    ("cherry red", "Cherry Red"),
    ("midnight blue", "Midnight Blue"),
    ("caramel pearl", "Caramel Pearl"),
    ("black olive", "Black Olive"),
    ("basil love", "Basil Love"),
    ("blue riviera", "Blue Riviera"),
    ("pastel pink", "Pastel Pink"),
    ("sweet pink", "Sweet Pink"),
    ("glossy havane", "Glossy Havane"),
    ("cookie dough", "Cookie Dough"),
    ("pomodoro", "Pomodoro"),
    ("pasty dream", "Pasty Dream"),
    ("pastry dream", "Pasty Dream"),
    ("light grey", "Light Grey"),
    ("grey lenses", "Grey Lenses"),
    ("green lenses", "Green Lenses"),
    ("brown lenses", "Brown Lenses"),
    ("sandstorm", "Sandstorm"),
    ("granit", "Granit"),
    ("hazel", "Hazel"),
    ("havane", "Havane"),
    ("macchiato", "Macchiato"),
    ("lavender", "Lavender"),
    ("sand", "Sand"),
    ("black", "Black"),
    ("white", "White"),
    ("tortoise", "Tortoise"),
]

CONCEPT_RULES = [
    ("split screen", "Split Screen"),
    ("flux sans habillage", "Flux Sans Habillage"),
    ("mosaique reading", "Mosaique Reading"),
    ("multi modèles", "Multi Modèles"),
    ("multi modeles", "Multi Modèles"),
    ("muli modèles", "Multi Modèles"),
    ("ugc in store", "UGC in Store"),
    ("le super cent", "UGC Influenceur"),
    ("unboxing", "Unboxing"),
    ("moma", "MoMa"),
    ("packshot", "Packshot"),
    ("still life", "Still Life"),
    ("outdoor adventure", "Outdoor Adventure"),
    ("attrape lunettes", "Attrape Lunettes"),
    ("accumulation", "Accumulation"),
    ("kv ss26", "KV Campagne"),
    ("porté", "Porté / Lifestyle"),
    ("portés", "Porté / Lifestyle"),
]

PRIX_RULES = [
    ("avec prix", "Avec prix"),
    ("sans prix", "Sans prix"),
]


def split_tokens(name):
    return [t.strip() for t in re.split(r"\s-\s", name) if t.strip()]


def match_full_string(name_lower, rules):
    for needle, label in rules:
        if needle in name_lower:
            return label
    return None


def match_token_set(tokens_lower, token_map):
    for tok in tokens_lower:
        if tok in token_map:
            return token_map[tok]
    # try startswith for hashtags with trailing text glued (rare)
    for tok in tokens_lower:
        for k, v in token_map.items():
            if tok == k:
                return v
    return None


def match_collection(tokens):
    for tok in tokens:
        t = tok.strip()
        tl = t.lower()
        if t.startswith("#"):
            return t.split()[0]  # e.g. "#Office", "#D", "#SNOW"
        if "glacier" in tl:
            return "GLACIER"
        if tl in COLLECTION_NAMED:
            return t.upper() if len(t) <= 3 else t.title() if tl not in (
                "crossroads", "permanent", "bonpoint", "alegria"
            ) else t.upper()
    return None


def parse_ad(name):
    name_lower = name.lower()
    tokens = split_tokens(name)
    tokens_lower = [t.lower() for t in tokens]

    fmt = match_full_string(name_lower, FORMAT_RULES)
    persona = match_token_set(tokens_lower, PERSONA_TOKENS)
    gamme = match_token_set(tokens_lower, GAMME_TOKENS)
    collection = match_collection(tokens)
    coloris = match_full_string(name_lower, COLORIS_RULES)
    concept = match_full_string(name_lower, CONCEPT_RULES)
    prix = match_full_string(name_lower, PRIX_RULES)

    return {
        "format": fmt,
        "persona": persona,
        "gamme": gamme,
        "collection": collection,
        "coloris": coloris,
        "concept": concept,
        "prix": prix,
    }


# ---------------------------------------------------------------------------
# Load + aggregate
# ---------------------------------------------------------------------------

def load_rows():
    rows = []
    with open(CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            cost = float(r["cost"] or 0)
            purchases = float(r["purchases"] or 0)
            conv_value = float(r["conv_value"] or 0)
            parsed = parse_ad(r["ad_name"])
            rows.append({
                "ad_name": r["ad_name"],
                "cost": cost,
                "purchases": purchases,
                "conv_value": conv_value,
                **parsed,
            })
    return rows


def aggregate(rows, field):
    buckets = defaultdict(lambda: {"spend": 0.0, "value": 0.0, "purchases": 0.0, "n_ads": 0})
    for r in rows:
        key = r[field]
        if not key:
            continue
        b = buckets[key]
        b["spend"] += r["cost"]
        b["value"] += r["conv_value"]
        b["purchases"] += r["purchases"]
        b["n_ads"] += 1
    out = []
    for key, b in buckets.items():
        roas = (b["value"] / b["spend"]) if b["spend"] > 0 else 0
        cpa = (b["spend"] / b["purchases"]) if b["purchases"] > 0 else None
        out.append({
            "label": key,
            "spend": round(b["spend"], 2),
            "value": round(b["value"], 2),
            "purchases": round(b["purchases"], 1),
            "n_ads": b["n_ads"],
            "roas": round(roas, 2),
            "cpa": round(cpa, 2) if cpa is not None else None,
        })
    out.sort(key=lambda x: x["spend"], reverse=True)
    return out


def coverage(rows, field):
    matched = sum(1 for r in rows if r[field])
    return matched, len(rows)


# ---------------------------------------------------------------------------
# Recommendations (rule-based, recomputed from current data every run)
# ---------------------------------------------------------------------------

def fmt_eur(x):
    return f"{x:,.0f} €".replace(",", " ")


def global_stats(rows):
    total_spend = sum(r["cost"] for r in rows)
    total_value = sum(r["conv_value"] for r in rows)
    avg_roas = total_value / total_spend if total_spend else 0
    return total_spend, total_value, avg_roas


def reco_persona(agg, avg_roas):
    if not agg:
        return "Pas assez de données nomenclaturées pour recommander."
    sorted_by_roas = sorted(agg, key=lambda x: x["roas"], reverse=True)
    best = sorted_by_roas[0]
    worst = sorted_by_roas[-1]
    low_volume_high_roas = [b for b in agg if b["roas"] > avg_roas and b["n_ads"] <= 3]
    lines = []
    lines.append(
        f"<b>{best['label']}</b> a le meilleur ROAS ({best['roas']}x) pour {fmt_eur(best['spend'])} "
        f"de spend sur {best['n_ads']} créas : c'est le persona le plus rentable, à prioriser dans le prochain "
        f"brief de production."
    )
    if worst["label"] != best["label"] and worst["spend"] > 0.05 * sum(b["spend"] for b in agg):
        lines.append(
            f"<b>{worst['label']}</b> a le ROAS le plus faible ({worst['roas']}x) malgré {fmt_eur(worst['spend'])} "
            f"de spend : challenger les concepts actuels ou réduire l'allocation avant de réinvestir."
        )
    if low_volume_high_roas:
        names = ", ".join(f"<b>{b['label']}</b> ({b['n_ads']} créa(s), {b['roas']}x)" for b in low_volume_high_roas)
        lines.append(
            f"Volume de créas trop faible malgré une bonne performance : {names}. Produire davantage de "
            f"déclinaisons pour ce(s) persona(s) avant qu'il(s) ne s'essouffle(nt)."
        )
    return " ".join(lines)


def reco_bubble(agg, avg_roas, variable_label):
    if not agg:
        return "Pas assez de données nomenclaturées pour recommander."
    sorted_by_roas = sorted(agg, key=lambda x: x["roas"], reverse=True)
    best = sorted_by_roas[0]
    total_spend = sum(b["spend"] for b in agg)
    big_spend_low_roas = [b for b in agg if b["spend"] > 0.1 * total_spend and b["roas"] < avg_roas]
    lines = [
        f"<b>{best['label']}</b> est le {variable_label.lower()} le plus performant (ROAS {best['roas']}x, "
        f"{fmt_eur(best['spend'])} de spend, {best['n_ads']} créas) : à privilégier dans les prochains tournages/réalisations."
    ]
    if big_spend_low_roas:
        names = ", ".join(f"<b>{b['label']}</b> ({b['roas']}x)" for b in big_spend_low_roas)
        lines.append(
            f"{names} concentre(nt) un budget important pour un ROAS sous la moyenne compte "
            f"({avg_roas:.2f}x) : à requestionner (créa, ciblage ou pression publicitaire)."
        )
    low_vol = [b for b in agg if b["roas"] >= avg_roas and b["n_ads"] <= 2]
    if low_vol:
        names = ", ".join(f"<b>{b['label']}</b>" for b in low_vol)
        lines.append(f"{names} performe(nt) bien mais avec très peu de créas testées : élargir la production.")
    return " ".join(lines)


def reco_bar(agg, avg_roas, variable_label, metric="roas"):
    if not agg:
        return "Pas assez de données nomenclaturées pour recommander."
    sorted_agg = sorted(agg, key=lambda x: (x[metric] if x[metric] is not None else -1), reverse=(metric == "roas"))
    if metric == "cpa":
        sorted_agg = sorted([b for b in agg if b["cpa"] is not None], key=lambda x: x["cpa"])
    if not sorted_agg:
        return "Pas assez de données nomenclaturées pour recommander."
    best = sorted_agg[0]
    worst = sorted_agg[-1]
    metric_label = "ROAS" if metric == "roas" else "CPA"
    best_val = best[metric]
    worst_val = worst[metric]
    lines = [
        f"<b>{best['label']}</b> affiche le meilleur {metric_label} ({best_val}{'x' if metric=='roas' else ' €'}) "
        f"sur {fmt_eur(best['spend'])} de spend ({best['n_ads']} créas) : allouer davantage de production à cette valeur."
    ]
    if worst["label"] != best["label"]:
        lines.append(
            f"<b>{worst['label']}</b> est en retrait ({metric_label} {worst_val}{'x' if metric=='roas' else ' €'}) : "
            f"limiter les nouvelles déclinaisons tant que la performance ne s'améliore pas."
        )
    return " ".join(lines)


def reco_prix(agg):
    if len(agg) < 2:
        return "Pas assez de données (Avec prix / Sans prix) pour comparer."
    by_label = {b["label"]: b for b in agg}
    avec = by_label.get("Avec prix")
    sans = by_label.get("Sans prix")
    if not avec or not sans:
        return "Pas assez de données (Avec prix / Sans prix) pour comparer."
    if avec["roas"] > sans["roas"]:
        winner, loser = avec, sans
    else:
        winner, loser = sans, avec
    return (
        f"<b>{winner['label']}</b> convertit mieux (ROAS {winner['roas']}x vs {loser['roas']}x pour "
        f"<b>{loser['label']}</b>) sur la période. Généraliser l'affichage \"{winner['label'].lower()}\" "
        f"sur les prochaines déclinaisons, en gardant un test A/B minoritaire sur l'autre variante pour ne pas perdre le signal."
    )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def main():
    rows = load_rows()
    total_spend, total_value, avg_roas = global_stats(rows)
    total_purchases = sum(r["purchases"] for r in rows)

    persona_agg = aggregate(rows, "persona")
    format_agg = aggregate(rows, "format")
    gamme_agg = aggregate(rows, "gamme")
    collection_agg = aggregate(rows, "collection")
    coloris_agg = aggregate(rows, "coloris")
    concept_agg = aggregate(rows, "concept")
    prix_agg = aggregate(rows, "prix")

    payload = {
        "meta": {
            "total_spend": round(total_spend, 2),
            "total_value": round(total_value, 2),
            "avg_roas": round(avg_roas, 2),
            "total_purchases": round(total_purchases, 1),
            "n_ads": len(rows),
            "period": "01/01/2026 -> aujourd'hui",
            "coverage": {
                "persona": coverage(rows, "persona"),
                "format": coverage(rows, "format"),
                "gamme": coverage(rows, "gamme"),
                "collection": coverage(rows, "collection"),
                "coloris": coverage(rows, "coloris"),
                "concept": coverage(rows, "concept"),
                "prix": coverage(rows, "prix"),
            },
        },
        "persona": persona_agg,
        "format": format_agg,
        "gamme": gamme_agg,
        "collection": collection_agg[:12],
        "coloris": coloris_agg[:12],
        "concept": concept_agg[:12],
        "prix": prix_agg,
        "reco": {
            "persona": reco_persona(persona_agg, avg_roas),
            "format": reco_bubble(format_agg, avg_roas, "Format"),
            "gamme": reco_bar(gamme_agg, avg_roas, "Gamme"),
            "collection": reco_bar(collection_agg[:12], avg_roas, "Collection", metric="cpa"),
            "coloris": reco_bar(coloris_agg[:12], avg_roas, "Coloris"),
            "concept": reco_bubble(concept_agg[:12], avg_roas, "Concept"),
            "prix": reco_prix(prix_agg),
        },
    }

    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(rows)} ads, spend={fmt_eur(total_spend)}, ROAS moyen={avg_roas:.2f}x)")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IZIPIZI - Creative Performance Dashboard (Meta Ads)</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  :root { --violet: #5A45FF; --dark: #171717; --green: #9CF694; --red: #FF4444; --grey: #F4F4F6; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; background: var(--grey); color: var(--dark); }
  header { background: var(--dark); color: #fff; padding: 28px 32px; }
  header h1 { margin: 0 0 6px 0; font-size: 22px; }
  header p { margin: 0; color: #bbb; font-size: 14px; }
  .kpis { display: flex; gap: 16px; padding: 20px 32px; flex-wrap: wrap; }
  .kpi { background: #fff; border-radius: 10px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.08); min-width: 160px; }
  .kpi .label { font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: .04em; }
  .kpi .value { font-size: 24px; font-weight: 700; color: var(--violet); margin-top: 4px; }
  main { padding: 8px 32px 48px; max-width: 1280px; margin: 0 auto; }
  section.card { background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 28px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  section.card h2 { margin: 0 0 4px 0; font-size: 18px; }
  section.card .sub { font-size: 13px; color: #888; margin-bottom: 12px; }
  .chart { width: 100%; height: 460px; }
  .reco { margin-top: 14px; padding: 14px 18px; background: #F1EEFF; border-left: 4px solid var(--violet); border-radius: 6px; font-size: 14px; line-height: 1.5; }
  .reco b { color: var(--violet); }
  footer { text-align: center; color: #999; font-size: 12px; padding: 20px; }
</style>
</head>
<body>
<header>
  <h1>IZIPIZI - Creative Performance Dashboard (Meta Ads)</h1>
  <p id="period-label"></p>
</header>
<div class="kpis" id="kpis"></div>
<main>

  <section class="card">
    <h2>Persona x ROAS x Spend x Volume de créas</h2>
    <div class="sub">Un point = un persona. X = spend, Y = ROAS, Z = nombre de créas rattachées à ce persona depuis le 01/01/2026.</div>
    <div id="chart-persona" class="chart"></div>
    <div class="reco" id="reco-persona"></div>
  </section>

  <section class="card">
    <h2>Format</h2>
    <div class="sub">Spend x ROAS x volume de créas par type de format.</div>
    <div id="chart-format" class="chart"></div>
    <div class="reco" id="reco-format"></div>
  </section>

  <section class="card">
    <h2>Gamme / Usage</h2>
    <div class="sub">ROAS par gamme produit (SUN, READING, SCREEN, SPORT, KIDS...).</div>
    <div id="chart-gamme" class="chart"></div>
    <div class="reco" id="reco-gamme"></div>
  </section>

  <section class="card">
    <h2>Collection / Ligne</h2>
    <div class="sub">CPA (coût par achat) par collection - top 12 par spend, du plus efficace au moins efficace.</div>
    <div id="chart-collection" class="chart"></div>
    <div class="reco" id="reco-collection"></div>
  </section>

  <section class="card">
    <h2>Coloris / Modèle</h2>
    <div class="sub">ROAS par coloris - top 12 par spend.</div>
    <div id="chart-coloris" class="chart"></div>
    <div class="reco" id="reco-coloris"></div>
  </section>

  <section class="card">
    <h2>Concept créatif</h2>
    <div class="sub">Spend x ROAS x volume de créas par concept de shooting/montage - top 12 par spend.</div>
    <div id="chart-concept" class="chart"></div>
    <div class="reco" id="reco-concept"></div>
  </section>

  <section class="card">
    <h2>Affichage du prix</h2>
    <div class="sub">Avec prix vs Sans prix.</div>
    <div id="chart-prix" class="chart"></div>
    <div class="reco" id="reco-prix"></div>
  </section>

</main>
<footer>Source : Supermetrics -> Facebook Ads (IZIPIZI FRANCE, act_10151142776889200) - Achats Website (attribution par défaut du compte) - Généré automatiquement</footer>

<script>
const DATA = __DATA__;
const VIOLET = "#5A45FF";
const PALETTE = ["#5A45FF","#171717","#FF4444","#9CF694","#FFB84D","#4DA1FF","#C64DFF","#4DFFD8","#FF4DA1","#B0B0B0"];

document.getElementById("period-label").textContent =
  `Période : ${DATA.meta.period} | ${DATA.meta.n_ads} ads avec spend | ${DATA.meta.total_purchases.toLocaleString('fr-FR')} achats`;

function euros(x) { return x.toLocaleString('fr-FR', {maximumFractionDigits:0}) + " €"; }

const kpis = document.getElementById("kpis");
[
  ["Spend total", euros(DATA.meta.total_spend)],
  ["Valeur de conversion", euros(DATA.meta.total_value)],
  ["ROAS moyen compte", DATA.meta.avg_roas + "x"],
  ["Achats", Math.round(DATA.meta.total_purchases).toLocaleString('fr-FR')],
].forEach(([label, value]) => {
  const el = document.createElement("div");
  el.className = "kpi";
  el.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
  kpis.appendChild(el);
});

// ---- Persona 3D ----
(function() {
  const d = DATA.persona;
  Plotly.newPlot("chart-persona", [{
    type: "scatter3d",
    mode: "markers+text",
    x: d.map(p => p.spend),
    y: d.map(p => p.roas),
    z: d.map(p => p.n_ads),
    text: d.map(p => p.label),
    textposition: "top center",
    marker: {
      size: d.map(p => Math.max(8, Math.min(28, p.n_ads * 1.5))),
      color: d.map((_, i) => PALETTE[i % PALETTE.length]),
      opacity: 0.9,
      line: { color: "#fff", width: 1 },
    },
  }], {
    margin: {l:0,r:0,t:10,b:0},
    scene: {
      xaxis: { title: "Spend (€)" },
      yaxis: { title: "ROAS" },
      zaxis: { title: "Volume de créas" },
    },
  }, {responsive:true, displaylogo:false});
  document.getElementById("reco-persona").innerHTML = DATA.reco.persona;
})();

function bubbleChart(divId, data, recoId, recoText) {
  Plotly.newPlot(divId, [{
    type: "scatter",
    mode: "markers+text",
    x: data.map(d => d.spend),
    y: data.map(d => d.roas),
    text: data.map(d => d.label),
    textposition: "top center",
    marker: {
      size: data.map(d => Math.max(14, Math.min(70, d.n_ads * 3))),
      color: data.map((_, i) => PALETTE[i % PALETTE.length]),
      opacity: 0.85,
      line: { color: "#fff", width: 1 },
    },
  }], {
    margin: {l:60,r:20,t:10,b:50},
    xaxis: { title: "Spend (€)" },
    yaxis: { title: "ROAS" },
  }, {responsive:true, displaylogo:false});
  document.getElementById(recoId).innerHTML = recoText;
}
bubbleChart("chart-format", DATA.format, "reco-format", DATA.reco.format);
bubbleChart("chart-concept", DATA.concept, "reco-concept", DATA.reco.concept);

function barChart(divId, data, recoId, recoText, metric, ascending) {
  let sorted = [...data].filter(d => d[metric] !== null && d[metric] !== undefined);
  sorted.sort((a,b) => ascending ? a[metric]-b[metric] : b[metric]-a[metric]);
  Plotly.newPlot(divId, [{
    type: "bar",
    orientation: "h",
    x: sorted.map(d => d[metric]).reverse(),
    y: sorted.map(d => d.label + `  (${euros(d.spend)}, ${d.n_ads} créas)`).reverse(),
    marker: { color: VIOLET },
  }], {
    margin: {l:260,r:20,t:10,b:50},
    xaxis: { title: metric === "roas" ? "ROAS" : "CPA (€)" },
  }, {responsive:true, displaylogo:false});
  document.getElementById(recoId).innerHTML = recoText;
}
barChart("chart-gamme", DATA.gamme, "reco-gamme", DATA.reco.gamme, "roas", false);
barChart("chart-collection", DATA.collection, "reco-collection", DATA.reco.collection, "cpa", true);
barChart("chart-coloris", DATA.coloris, "reco-coloris", DATA.reco.coloris, "roas", false);

(function() {
  const d = DATA.prix;
  Plotly.newPlot("chart-prix", [
    { type:"bar", name:"ROAS", x: d.map(x=>x.label), y: d.map(x=>x.roas), marker:{color:VIOLET}, yaxis:"y" },
  ], {
    margin: {l:60,r:20,t:10,b:50},
    yaxis: { title: "ROAS" },
    barmode: "group",
  }, {responsive:true, displaylogo:false});
  document.getElementById("reco-prix").innerHTML = DATA.reco.prix;
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
