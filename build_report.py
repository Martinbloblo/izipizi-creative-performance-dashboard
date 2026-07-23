#!/usr/bin/env python3
"""
IZIPIZI Meta Ads - Creative Performance Dashboard builder (v2).

Two data sources:
  - data_raw.csv   : ad-level totals since Jan 1st (ad_name, cost, purchases,
                      conv_value). Used ONLY to compute the STABLE
                      recommendations + ideation bullets (server-side, once
                      per run) so they never move because of client-side
                      date-range / persona filtering.
  - data_daily.csv  : per-ad, per-day rows for a rolling 90-day window
                      (date, ad_name, cost, purchases, conv_value). Embedded
                      client-side so the browser can filter by date range
                      (7j/30j/90j presets) and by persona, recomputing every
                      chart and KPI on the fly.

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
DAILY_CSV_PATH = ROOT / "data_daily.csv"
MARKET_CSV_PATH = ROOT / "data_market_raw.csv"
MARKET_DAILY_CSV_PATH = ROOT / "data_market_daily.csv"
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

# Market is parsed from the CAMPAIGN name (not the ad name): client's campaign
# nomenclature embeds a 2-letter country code in parentheses, e.g.
# "ASUC-(HISTO)-US-(US)-PERF-ACQ-COLD" or "ASUC-(NEW)-SUISSE-(CH)-PERF-RTG".
# Campaigns without such a code (INTER, ROW, multi-market catalog, branding/
# organic posts) don't map to a single market and are excluded from this
# chart only (same "non-conforming" policy as the other nomenclature fields).
MARKET_NAMES = {
    "FR": "France", "US": "USA", "UK": "UK", "DE": "Allemagne", "CH": "Suisse",
    "IT": "Italie", "BE": "Belgique", "ES": "Espagne", "AT": "Autriche",
    "CA": "Canada", "NL": "Pays-Bas", "AU": "Australie", "PT": "Portugal",
    "MX": "Mexique", "PL": "Pologne", "NO": "Norvège", "SE": "Suède",
    "HR": "Croatie", "MO": "Moyen-Orient",
}


def parse_market(campaign_name):
    m = re.search(r"\(([A-Z]{2})\)", campaign_name)
    if not m:
        return None
    code = m.group(1)
    return MARKET_NAMES.get(code, code)


def safe_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


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
    """Ad-level totals since Jan 1st (data_raw.csv) - used for stable reco/ideation."""
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


def load_daily_rows():
    """Per-ad, per-day rows (data_daily.csv) - used for the interactive charts."""
    rows = []
    with open(DAILY_CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            cost = float(r["cost"] or 0)
            purchases = float(r["purchases"] or 0)
            conv_value = float(r["conv_value"] or 0)
            parsed = parse_ad(r["ad_name"])
            rows.append({
                "date": r["date"],
                "ad_name": r["ad_name"],
                "cost": cost,
                "purchases": purchases,
                "conv_value": conv_value,
                **parsed,
            })
    return rows


def load_market_rows():
    """Campaign-level totals since Jan 1st (data_market_raw.csv) - stable market reco/ideation."""
    rows = []
    with open(MARKET_CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "campaign_name": r["campaign_name"],
                "cost": safe_float(r["cost"]),
                "purchases": safe_float(r["purchases"]),
                "conv_value": safe_float(r["conv_value"]),
                "market": parse_market(r["campaign_name"]),
            })
    return rows


def load_market_daily_rows():
    """Per-campaign, per-day rows (data_market_daily.csv) - interactive market chart."""
    rows = []
    with open(MARKET_DAILY_CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "date": r["date"],
                "campaign_name": r["campaign_name"],
                "cost": safe_float(r["cost"]),
                "purchases": safe_float(r["purchases"]),
                "conv_value": safe_float(r["conv_value"]),
                "market": parse_market(r["campaign_name"]),
            })
    return rows


def aggregate_market(rows):
    buckets = defaultdict(lambda: {"spend": 0.0, "value": 0.0, "purchases": 0.0, "campaigns": set()})
    for r in rows:
        key = r["market"]
        if not key:
            continue
        b = buckets[key]
        b["spend"] += r["cost"]
        b["value"] += r["conv_value"]
        b["purchases"] += r["purchases"]
        b["campaigns"].add(r["campaign_name"])
    out = []
    for key, b in buckets.items():
        roas = (b["value"] / b["spend"]) if b["spend"] > 0 else 0
        out.append({
            "label": key,
            "spend": round(b["spend"], 2),
            "value": round(b["value"], 2),
            "purchases": round(b["purchases"], 1),
            "n_campaigns": len(b["campaigns"]),
            "roas": round(roas, 2),
        })
    out.sort(key=lambda x: x["spend"], reverse=True)
    return out


def aggregate(rows, field):
    buckets = defaultdict(lambda: {"spend": 0.0, "value": 0.0, "purchases": 0.0, "ads": set()})
    for r in rows:
        key = r[field]
        if not key:
            continue
        b = buckets[key]
        b["spend"] += r["cost"]
        b["value"] += r["conv_value"]
        b["purchases"] += r["purchases"]
        b["ads"].add(r.get("ad_name", key))
    out = []
    for key, b in buckets.items():
        roas = (b["value"] / b["spend"]) if b["spend"] > 0 else 0
        cpa = (b["spend"] / b["purchases"]) if b["purchases"] > 0 else None
        out.append({
            "label": key,
            "spend": round(b["spend"], 2),
            "value": round(b["value"], 2),
            "purchases": round(b["purchases"], 1),
            "n_ads": len(b["ads"]),
            "roas": round(roas, 2),
            "cpa": round(cpa, 2) if cpa is not None else None,
        })
    out.sort(key=lambda x: x["spend"], reverse=True)
    return out


def coverage(rows, field):
    matched = sum(1 for r in rows if r[field])
    return matched, len(rows)


# ---------------------------------------------------------------------------
# Recommendations (rule-based, computed ONCE from the full since-Jan-1
# dataset - deliberately decoupled from the client-side date/persona
# filters so the text stays stable day to day).
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


def reco_market(agg):
    if not agg:
        return "Pas assez de données nomenclaturées pour recommander."
    total_spend = sum(b["spend"] for b in agg)
    total_value = sum(b["value"] for b in agg)
    avg_roas = total_value / total_spend if total_spend else 0
    sorted_by_roas = sorted(agg, key=lambda x: x["roas"], reverse=True)
    best = sorted_by_roas[0]
    worst = sorted_by_roas[-1]
    lines = [
        f"<b>{best['label']}</b> est le marché le plus rentable (ROAS {best['roas']}x pour {fmt_eur(best['spend'])} "
        f"de spend) : prioriser les prochains investissements média sur ce marché."
    ]
    if worst["label"] != best["label"] and worst["spend"] > 0.03 * total_spend:
        lines.append(
            f"<b>{worst['label']}</b> affiche le ROAS le plus faible ({worst['roas']}x) malgré {fmt_eur(worst['spend'])} "
            f"de spend : challenger le ciblage/créa local ou réduire l'allocation avant de réinvestir."
        )
    big_spend_low_roas = [
        b for b in agg
        if b["spend"] > 0.1 * total_spend and b["roas"] < avg_roas and b["label"] not in (best["label"], worst["label"])
    ]
    if big_spend_low_roas:
        names = ", ".join(f"<b>{b['label']}</b> ({b['roas']}x)" for b in big_spend_low_roas)
        lines.append(
            f"{names} concentre(nt) un budget important pour un ROAS sous la moyenne compte ({avg_roas:.2f}x) : "
            f"à requestionner (ciblage, créa locale ou pression publicitaire)."
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
# Ideation bullets (3 per chart, stable - same source data as the reco above)
# ---------------------------------------------------------------------------

def ideas_market(agg):
    if not agg:
        return []
    ranked = sorted(agg, key=lambda x: x["roas"], reverse=True)
    best, worst = ranked[0], ranked[-1]
    return [
        f"Augmenter le budget média sur <b>{best['label']}</b> pour capitaliser sur son ROAS.",
        f"Auditer le ciblage et les créas locales sur <b>{worst['label']}</b> avant de réinvestir davantage.",
        f"Tester une déclinaison des codes créatifs qui fonctionnent sur <b>{best['label']}</b> sur des marchés proches culturellement.",
    ]


def ideas_persona(agg):
    if not agg:
        return []
    ranked = sorted(agg, key=lambda x: x["roas"], reverse=True)
    best, worst = ranked[0], ranked[-1]
    return [
        f"Décliner <b>{best['label']}</b> en 2-3 nouveaux formats courts (UGC + Motion) pour capitaliser sur son ROAS.",
        f"Retravailler <b>{worst['label']}</b> avec le style créatif (cadrage, accroche, montage) qui fonctionne pour <b>{best['label']}</b>.",
        f"Tester une nouvelle déclinaison produit/collection sur le persona <b>{best['label']}</b> pour vérifier la scalabilité de sa performance.",
    ]


def ideas_format(agg):
    if not agg:
        return []
    ranked = sorted(agg, key=lambda x: x["roas"], reverse=True)
    best, worst = ranked[0], ranked[-1]
    return [
        f"Produire 2-3 nouvelles versions du format <b>{best['label']}</b> sur d'autres personas/gammes pour dupliquer sa performance.",
        f"Tester une version courte (6-10s) ou un montage plus dynamique du format <b>{worst['label']}</b> pour challenger son ROAS.",
        f"Croiser les codes du format <b>{best['label']}</b> (rythme, texte à l'écran, accroche) avec un concept créatif différent.",
    ]


def ideas_gamme(agg):
    if not agg:
        return []
    ranked = sorted(agg, key=lambda x: x["roas"], reverse=True)
    best, worst = ranked[0], ranked[-1]
    return [
        f"Prioriser le prochain shooting produit sur la gamme <b>{best['label']}</b>, moteur de performance actuel.",
        f"Tester un nouvel angle créatif (usage, mise en situation) pour relancer la gamme <b>{worst['label']}</b>.",
        f"Décliner un mini-plan média dédié à <b>{best['label']}</b> avec 2-3 nouveaux visuels pour confirmer la tendance.",
    ]


def ideas_collection(agg):
    ranked = sorted([b for b in agg if b["cpa"] is not None], key=lambda x: x["cpa"])
    if not ranked:
        return []
    best, worst = ranked[0], ranked[-1]
    return [
        f"Renouveler 2-3 créas sur la collection <b>{best['label']}</b> (meilleur CPA) pour prolonger sa dynamique.",
        f"Retester la collection <b>{worst['label']}</b> avec un nouveau format ou un nouveau prix affiché avant de réduire son budget.",
        f"Croiser <b>{best['label']}</b> avec un persona ou une gamme peu exploités pour élargir son audience.",
    ]


def ideas_coloris(agg):
    if not agg:
        return []
    ranked = sorted(agg, key=lambda x: x["roas"], reverse=True)
    best, worst = ranked[0], ranked[-1]
    return [
        f"Décliner le coloris <b>{best['label']}</b> sur d'autres montures/collections encore non testées.",
        f"Retravailler le visuel du coloris <b>{worst['label']}</b> (fond, lumière, mise en situation).",
        f"Prévoir un carrousel dédié mettant en avant les coloris les plus performants dont <b>{best['label']}</b>.",
    ]


def ideas_concept(agg):
    if not agg:
        return []
    ranked = sorted(agg, key=lambda x: x["roas"], reverse=True)
    best, worst = ranked[0], ranked[-1]
    return [
        f"Dupliquer le concept <b>{best['label']}</b> sur de nouveaux produits/collections à venir.",
        f"Refaire le concept <b>{worst['label']}</b> avec un nouveau talent/mise en scène avant de l'abandonner.",
        f"Tester un hybride entre <b>{best['label']}</b> et un autre concept fort pour renouveler le stock créatif.",
    ]


def ideas_prix(agg):
    by_label = {b["label"]: b for b in agg}
    avec, sans = by_label.get("Avec prix"), by_label.get("Sans prix")
    if not avec or not sans:
        return []
    winner = avec["label"] if avec["roas"] >= sans["roas"] else sans["label"]
    loser = sans["label"] if winner == avec["label"] else avec["label"]
    return [
        f"Généraliser l'affichage \"{winner.lower()}\" sur les prochaines déclinaisons carrousel/image.",
        f"Garder un test A/B minoritaire (10-20% du budget) sur \"{loser.lower()}\" pour ne pas perdre le signal.",
        f"Tester une variante intermédiaire (prix barré / prix promo) pour voir si elle capte le meilleur des deux approches.",
    ]


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_daily_payload():
    daily_rows = load_daily_rows()

    ad_names = sorted({r["ad_name"] for r in daily_rows})
    ad_index = {name: i for i, name in enumerate(ad_names)}

    compact_rows = []
    for r in daily_rows:
        compact_rows.append([
            r["date"],
            ad_index[r["ad_name"]],
            round(r["cost"], 2),
            round(r["purchases"], 1),
            round(r["conv_value"], 2),
            r["persona"],
            r["format"],
            r["gamme"],
            r["collection"],
            r["coloris"],
            r["concept"],
            r["prix"],
        ])

    dates = sorted({r["date"] for r in daily_rows})
    persona_order = [p["label"] for p in aggregate(daily_rows, "persona")]

    return {
        "ad_names": ad_names,
        "field_order": ["date", "ad_idx", "cost", "purchases", "conv_value",
                         "persona", "format", "gamme", "collection", "coloris",
                         "concept", "prix"],
        "rows": compact_rows,
        "date_min": dates[0] if dates else None,
        "date_max": dates[-1] if dates else None,
        "persona_order": persona_order,
    }


def build_market_daily_payload():
    rows = load_market_daily_rows()
    dates = sorted({r["date"] for r in rows})
    compact_rows = [
        [r["date"], r["market"], round(r["cost"], 2), round(r["purchases"], 1), round(r["conv_value"], 2)]
        for r in rows if r["market"]
    ]
    return {
        "rows": compact_rows,
        "date_min": dates[0] if dates else None,
        "date_max": dates[-1] if dates else None,
    }


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

    market_rows = load_market_rows()
    market_agg = aggregate_market(market_rows)

    daily = build_daily_payload()
    market_daily = build_market_daily_payload()

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
        "reco": {
            "market": reco_market(market_agg),
            "persona": reco_persona(persona_agg, avg_roas),
            "format": reco_bubble(format_agg, avg_roas, "Format"),
            "gamme": reco_bar(gamme_agg, avg_roas, "Gamme"),
            "collection": reco_bar(collection_agg[:12], avg_roas, "Collection", metric="cpa"),
            "coloris": reco_bar(coloris_agg[:12], avg_roas, "Coloris"),
            "concept": reco_bubble(concept_agg[:12], avg_roas, "Concept"),
            "prix": reco_prix(prix_agg),
        },
        "ideas": {
            "market": ideas_market(market_agg),
            "persona": ideas_persona(persona_agg),
            "format": ideas_format(format_agg),
            "gamme": ideas_gamme(gamme_agg),
            "collection": ideas_collection(collection_agg[:12]),
            "coloris": ideas_coloris(coloris_agg[:12]),
            "concept": ideas_concept(concept_agg[:12]),
            "prix": ideas_prix(prix_agg),
        },
        "daily": daily,
        "market_daily": market_daily,
    }

    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    OUT_PATH.write_text(html, encoding="utf-8")
    print(
        f"Wrote {OUT_PATH} ({len(rows)} ads since Jan 1, spend={fmt_eur(total_spend)}, "
        f"ROAS moyen={avg_roas:.2f}x | daily window {daily['date_min']} -> {daily['date_max']}, "
        f"{len(daily['rows'])} rows, {len(daily['ad_names'])} ads | "
        f"market: {len(market_agg)} markets, {len(market_daily['rows'])} daily rows)"
    )


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
  .filters { display: flex; flex-wrap: wrap; gap: 20px; align-items: center; padding: 16px 32px; background: #fff; border-bottom: 1px solid #eee; position: sticky; top: 0; z-index: 5; }
  .filter-group { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .filter-group label { font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: .04em; }
  .preset-btn, .persona-pill { border: 1px solid #ddd; background: #fff; border-radius: 20px; padding: 6px 14px; font-size: 13px; cursor: pointer; color: var(--dark); transition: all .15s; }
  .preset-btn:hover, .persona-pill:hover { border-color: var(--violet); }
  .preset-btn.active, .persona-pill.active { background: var(--violet); border-color: var(--violet); color: #fff; }
  input[type=date] { border: 1px solid #ddd; border-radius: 8px; padding: 5px 8px; font-size: 13px; }
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
  .reco-caption { font-size: 11px; color: #999; margin-top: 8px; font-style: italic; }
  .ideas { margin-top: 10px; padding: 14px 18px; background: #FAFAFA; border-left: 4px solid var(--dark); border-radius: 6px; font-size: 14px; line-height: 1.6; }
  .ideas b { color: var(--dark); }
  .ideas ul { margin: 4px 0 0 0; padding-left: 18px; }
  .ideas-title { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #888; font-weight: 700; }
  footer { text-align: center; color: #999; font-size: 12px; padding: 20px; }
</style>
</head>
<body>
<header>
  <h1>IZIPIZI - Creative Performance Dashboard (Meta Ads)</h1>
  <p id="period-label"></p>
</header>

<div class="filters">
  <div class="filter-group">
    <label>Période</label>
    <button class="preset-btn" data-preset="7">7j</button>
    <button class="preset-btn" data-preset="30">30j</button>
    <button class="preset-btn active" data-preset="90">90j</button>
    <input type="date" id="date-start">
    <span>&rarr;</span>
    <input type="date" id="date-end">
  </div>
  <div class="filter-group" id="persona-pills">
    <label>Persona</label>
  </div>
</div>

<div class="kpis" id="kpis"></div>
<main>

  <section class="card">
    <h2>Vue Marché</h2>
    <div class="sub">Spend x ROAS par marché (FR, US, UK...), extrait de la nomenclature de campagne - triée par spend.</div>
    <div id="chart-market" class="chart"></div>
    <div class="reco" id="reco-market"></div>
    <div class="ideas" id="ideas-market"></div>
    <div class="reco-caption">Recommandation et idées basées sur la période complète (01/01 &rarr; aujourd'hui) - ne varient pas avec les filtres ci-dessus.</div>
  </section>

  <section class="card">
    <h2>Persona x Spend x Volume de créas x ROAS</h2>
    <div class="sub">Une montagne = un persona. X = spend, Y = volume de créas, hauteur (Z) = ROAS.</div>
    <div id="chart-persona" class="chart"></div>
    <div class="reco" id="reco-persona"></div>
    <div class="ideas" id="ideas-persona"></div>
    <div class="reco-caption">Recommandation et idées basées sur la période complète (01/01 &rarr; aujourd'hui) - ne varient pas avec les filtres ci-dessus.</div>
  </section>

  <section class="card">
    <h2>Format</h2>
    <div class="sub">Spend x ROAS x volume de créas par type de format.</div>
    <div id="chart-format" class="chart"></div>
    <div class="reco" id="reco-format"></div>
    <div class="ideas" id="ideas-format"></div>
    <div class="reco-caption">Recommandation et idées basées sur la période complète (01/01 &rarr; aujourd'hui) - ne varient pas avec les filtres ci-dessus.</div>
  </section>

  <section class="card">
    <h2>Gamme / Usage</h2>
    <div class="sub">ROAS par gamme produit, triée par spend (SUN, READING, SCREEN, SPORT, KIDS...).</div>
    <div id="chart-gamme" class="chart"></div>
    <div class="reco" id="reco-gamme"></div>
    <div class="ideas" id="ideas-gamme"></div>
    <div class="reco-caption">Recommandation et idées basées sur la période complète (01/01 &rarr; aujourd'hui) - ne varient pas avec les filtres ci-dessus.</div>
  </section>

  <section class="card">
    <h2>Collection / Ligne</h2>
    <div class="sub">CPA (coût par achat) par collection - top 12, triée par spend.</div>
    <div id="chart-collection" class="chart"></div>
    <div class="reco" id="reco-collection"></div>
    <div class="ideas" id="ideas-collection"></div>
    <div class="reco-caption">Recommandation et idées basées sur la période complète (01/01 &rarr; aujourd'hui) - ne varient pas avec les filtres ci-dessus.</div>
  </section>

  <section class="card">
    <h2>Coloris / Modèle</h2>
    <div class="sub">ROAS par coloris - top 12 par spend.</div>
    <div id="chart-coloris" class="chart"></div>
    <div class="reco" id="reco-coloris"></div>
    <div class="ideas" id="ideas-coloris"></div>
    <div class="reco-caption">Recommandation et idées basées sur la période complète (01/01 &rarr; aujourd'hui) - ne varient pas avec les filtres ci-dessus.</div>
  </section>

  <section class="card">
    <h2>Concept créatif</h2>
    <div class="sub">Spend x ROAS x volume de créas par concept de shooting/montage - top 12 par spend.</div>
    <div id="chart-concept" class="chart"></div>
    <div class="reco" id="reco-concept"></div>
    <div class="ideas" id="ideas-concept"></div>
    <div class="reco-caption">Recommandation et idées basées sur la période complète (01/01 &rarr; aujourd'hui) - ne varient pas avec les filtres ci-dessus.</div>
  </section>

  <section class="card">
    <h2>Affichage du prix</h2>
    <div class="sub">Avec prix vs Sans prix.</div>
    <div id="chart-prix" class="chart"></div>
    <div class="reco" id="reco-prix"></div>
    <div class="ideas" id="ideas-prix"></div>
    <div class="reco-caption">Recommandation et idées basées sur la période complète (01/01 &rarr; aujourd'hui) - ne varient pas avec les filtres ci-dessus.</div>
  </section>

</main>
<footer>Source : Supermetrics -> Facebook Ads (IZIPIZI FRANCE, act_10151142776889200) - Achats Website (attribution par défaut du compte) - Généré automatiquement</footer>

<script>
const DATA = __DATA__;
const VIOLET = "#5A45FF";
const DARK = "#171717";
const GREY_OUT = "#DADADA";
const PALETTE = ["#5A45FF","#171717","#FF4444","#9CF694","#FFB84D","#4DA1FF","#C64DFF","#4DFFD8","#FF4DA1","#B0B0B0"];

// row field indices (see build_daily_payload in build_report.py)
const F = { date:0, ad_idx:1, cost:2, purchases:3, conv_value:4, persona:5, format:6, gamme:7, collection:8, coloris:9, concept:10, prix:11 };
const RAW = DATA.daily.rows;
const AD_NAMES = DATA.daily.ad_names;

// Market rows: [date, market_label, cost, purchases, conv_value]
const FM = { date:0, market:1, cost:2, purchases:3, conv_value:4 };
const MARKET_RAW = DATA.market_daily.rows;

function euros(x) { return x.toLocaleString('fr-FR', {maximumFractionDigits:0}) + " €"; }

// ---- Recos + ideas (static, from full-period data) ----
["market","persona","format","gamme","collection","coloris","concept","prix"].forEach(key => {
  document.getElementById("reco-" + key).innerHTML = DATA.reco[key];
  const ideas = DATA.ideas[key] || [];
  const box = document.getElementById("ideas-" + key);
  if (ideas.length) {
    box.innerHTML = '<div class="ideas-title">Idées d\'itération / idéation</div><ul>' +
      ideas.map(i => `<li>${i}</li>`).join("") + '</ul>';
  }
});

// ---- Aggregation (mirrors Python's aggregate()) ----
function aggregateJS(rows, fieldKey) {
  const idx = F[fieldKey];
  const buckets = new Map();
  for (const r of rows) {
    const key = r[idx];
    if (!key) continue;
    if (!buckets.has(key)) buckets.set(key, { spend: 0, value: 0, purchases: 0, ads: new Set() });
    const b = buckets.get(key);
    b.spend += r[F.cost];
    b.value += r[F.conv_value];
    b.purchases += r[F.purchases];
    b.ads.add(r[F.ad_idx]);
  }
  const out = [];
  for (const [label, b] of buckets) {
    const roas = b.spend > 0 ? b.value / b.spend : 0;
    const cpa = b.purchases > 0 ? b.spend / b.purchases : null;
    out.push({ label, spend: b.spend, value: b.value, purchases: b.purchases, n_ads: b.ads.size, roas, cpa });
  }
  out.sort((a, b) => b.spend - a.spend);
  return out;
}

// ---- Filter state ----
let currentPersona = "Tous";
const dateStartEl = document.getElementById("date-start");
const dateEndEl = document.getElementById("date-end");

dateStartEl.min = dateEndEl.min = DATA.daily.date_min;
dateStartEl.max = dateEndEl.max = DATA.daily.date_max;

function applyPreset(days) {
  const end = DATA.daily.date_max;
  const endDate = new Date(end + "T00:00:00Z");
  const startDate = new Date(endDate.getTime() - (days - 1) * 86400000);
  const minDate = new Date(DATA.daily.date_min + "T00:00:00Z");
  const start = (startDate < minDate ? minDate : startDate).toISOString().slice(0, 10);
  dateStartEl.value = start;
  dateEndEl.value = end;
}
applyPreset(90);

document.querySelectorAll(".preset-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".preset-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    applyPreset(parseInt(btn.dataset.preset, 10));
    update();
  });
});
[dateStartEl, dateEndEl].forEach(el => el.addEventListener("change", () => {
  document.querySelectorAll(".preset-btn").forEach(b => b.classList.remove("active"));
  update();
}));

// ---- Persona pills ----
const pillsBox = document.getElementById("persona-pills");
["Tous", ...DATA.daily.persona_order].forEach(label => {
  const btn = document.createElement("button");
  btn.className = "persona-pill" + (label === "Tous" ? " active" : "");
  btn.textContent = label;
  btn.addEventListener("click", () => {
    document.querySelectorAll(".persona-pill").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentPersona = label;
    update();
  });
  pillsBox.appendChild(btn);
});

function rowsInDateRange() {
  const start = dateStartEl.value, end = dateEndEl.value;
  return RAW.filter(r => r[F.date] >= start && r[F.date] <= end);
}
function marketRowsInDateRange() {
  const start = dateStartEl.value, end = dateEndEl.value;
  return MARKET_RAW.filter(r => r[FM.date] >= start && r[FM.date] <= end);
}
// Market aggregation: Spend + ROAS only (no persona/volume dimension), grouped
// by market label. Kept separate from aggregateJS() since market rows don't
// carry an ad_idx to count distinct creatives.
function aggregateMarketJS(rows) {
  const buckets = new Map();
  for (const r of rows) {
    const key = r[FM.market];
    if (!key) continue;
    if (!buckets.has(key)) buckets.set(key, { spend: 0, value: 0, purchases: 0 });
    const b = buckets.get(key);
    b.spend += r[FM.cost];
    b.value += r[FM.conv_value];
    b.purchases += r[FM.purchases];
  }
  const out = [];
  for (const [label, b] of buckets) {
    const roas = b.spend > 0 ? b.value / b.spend : 0;
    out.push({ label, spend: b.spend, value: b.value, purchases: b.purchases, roas });
  }
  out.sort((a, b) => b.spend - a.spend); // always spend-descending, like Gamme/Collection
  return out;
}
function marketBarChart(data) {
  Plotly.react("chart-market", [{
    type: "bar",
    orientation: "h",
    x: data.map(d => d.roas).reverse(),
    y: data.map(d => d.label + `  (${euros(d.spend)})`).reverse(),
    marker: { color: VIOLET },
  }], {
    margin: {l:160,r:20,t:10,b:50},
    xaxis: { title: "ROAS" },
  }, {responsive:true, displaylogo:false});
}
function filteredRows() {
  const rows = rowsInDateRange();
  if (currentPersona === "Tous") return rows;
  return rows.filter(r => r[F.persona] === currentPersona);
}

function renderKPIs(rows) {
  const spend = rows.reduce((s, r) => s + r[F.cost], 0);
  const value = rows.reduce((s, r) => s + r[F.conv_value], 0);
  const purchases = rows.reduce((s, r) => s + r[F.purchases], 0);
  const roas = spend > 0 ? value / spend : 0;
  const kpis = document.getElementById("kpis");
  kpis.innerHTML = "";
  [
    ["Spend (période sélectionnée)", euros(spend)],
    ["Valeur de conversion", euros(value)],
    ["ROAS moyen", roas.toFixed(2) + "x"],
    ["Achats", Math.round(purchases).toLocaleString('fr-FR')],
  ].forEach(([label, val]) => {
    const el = document.createElement("div");
    el.className = "kpi";
    el.innerHTML = `<div class="label">${label}</div><div class="value">${val}</div>`;
    kpis.appendChild(el);
  });
}

// ---- Persona "mountain" chart (smooth surface, swapped axes: Y=volume, Z=ROAS) ----
// Spend/volume/ROAS live on wildly different scales (up to ~300k€ vs ~100 créas
// vs ~0-5x ROAS), so all three axes are normalized to 0-1 (relabeled with real
// values via tickvals/ticktext) to keep the terrain geometry sane and comparable.
//
// Each persona is a smooth Gaussian "bump" on a shared grid, combined via max()
// so overlapping bumps don't add up unrealistically. Peak HEIGHT = normalized
// ROAS (exact per persona). Bump WIDTH/footprint (sigma) scales with n_ads
// (volume of creatives), so a persona with more creatives renders as a visibly
// bigger/wider mountain, independent of its ROAS-driven height.
// Elevation is colored on a green -> yellow -> orange -> red scale, low (valley,
// low ROAS) to high (peak, high ROAS) - per explicit user-specified order. When
// a single persona is selected via the pills, non-selected mountains are
// recolored to flat grey via a separate `surfacecolor` array (decoupled from
// the `z` elevation, which still shows every persona's shape).
function renderPersonaChart(dateFilteredRows) {
  const agg = aggregateJS(dateFilteredRows, "persona");
  if (!agg.length) { Plotly.react("chart-persona", [], {}); return; }
  const spendMax = Math.max(...agg.map(p => p.spend), 1);
  const nMax = Math.max(...agg.map(p => p.n_ads), 1);
  const roasMax = Math.max(...agg.map(p => p.roas), 1);

  // sigma (bump width/footprint) scales with n_ads so mountains with more
  // creatives are visibly bigger/wider, not just taller by ROAS. Kept narrower
  // than the raw spend/volume spacing between personas so mountains stay
  // visually separated (with clear "valleys" between them) instead of merging
  // into a single blob when two personas sit close together on the grid.
  const SIGMA_MIN = 0.05, SIGMA_MAX = 0.13;
  const points = agg.map(p => ({
    label: p.label,
    x: p.spend / spendMax,
    y: p.n_ads / nMax,
    z: Math.max(p.roas / roasMax, 0.04),
    sigma: SIGMA_MIN + (p.n_ads / nMax) * (SIGMA_MAX - SIGMA_MIN),
    spend: p.spend, n_ads: p.n_ads, roas: p.roas,
  }));

  const GRID_N = 55;
  const AXIS_MAX = 1.15;
  const coords = Array.from({ length: GRID_N }, (_, i) => (i / (GRID_N - 1)) * AXIS_MAX);

  const zGrid = [];
  const colorGrid = [];
  for (const yy of coords) {
    const zRow = [];
    const cRow = [];
    for (const xx of coords) {
      let peakZ = 0;
      let peakActive = true;
      for (const pt of points) {
        const d2 = ((xx - pt.x) ** 2 + (yy - pt.y) ** 2) / (2 * pt.sigma * pt.sigma);
        const h = pt.z * Math.exp(-d2);
        if (h > peakZ) {
          peakZ = h;
          peakActive = currentPersona === "Tous" || currentPersona === pt.label;
        }
      }
      zRow.push(peakZ);
      cRow.push(peakActive ? peakZ : -1); // -1 = sentinel -> flat grey via colorscale below
    }
    zGrid.push(zRow);
    colorGrid.push(cRow);
  }

  // Colorscale over surfacecolor range [-1, 1]: values <0 (inactive persona) render
  // flat grey; values [0,1] (elevation, low -> high) render the
  // green (base/low ROAS) -> yellow -> orange -> red (peak/high ROAS) gradient,
  // per explicit user order ("vert, jaune, orange, rouge" from valley to peak).
  const colorscale = [
    [0, GREY_OUT], [0.4999, GREY_OUT],
    [0.5, "#4CAF50"], [0.67, "#FFD54D"], [0.84, "#FFA733"], [1, "#FF4444"],
  ];

  const surfaceTrace = {
    type: "surface",
    x: coords, y: coords, z: zGrid,
    surfacecolor: colorGrid,
    cmin: -1, cmax: 1,
    colorscale: colorscale,
    showscale: false,
    lighting: { ambient: 0.65, diffuse: 0.7, roughness: 0.5, specular: 0.15 },
    contours: { z: { show: false } },
    hoverinfo: "skip",
  };

  const labelTrace = {
    type: "scatter3d", mode: "markers+text",
    x: points.map(p => p.x), y: points.map(p => p.y), z: points.map(p => p.z + 0.1),
    text: points.map(p => p.label),
    textposition: "top center",
    marker: { size: 3, color: "#171717" },
    hovertemplate: points.map(p =>
      `<b>${p.label}</b><br>Spend: ${euros(p.spend)}<br>Volume: ${p.n_ads} créas<br>ROAS: ${p.roas.toFixed(2)}x<extra></extra>`
    ),
    showlegend: false,
  };

  const axisTicks = (maxVal, isEuro) => {
    const fracs = [0, 0.25, 0.5, 0.75, 1];
    return {
      tickvals: fracs,
      ticktext: fracs.map(f => isEuro ? euros(f * maxVal) : Math.round(f * maxVal).toLocaleString('fr-FR')),
    };
  };

  Plotly.react("chart-persona", [surfaceTrace, labelTrace], {
    margin: { l: 0, r: 0, t: 10, b: 0 },
    scene: {
      xaxis: Object.assign({ title: "Spend (€)", range: [0, AXIS_MAX] }, axisTicks(spendMax, true)),
      yaxis: Object.assign({ title: "Volume de créas", range: [0, AXIS_MAX] }, axisTicks(nMax, false)),
      zaxis: Object.assign({ title: "ROAS", range: [0, 1.3] }, {
        tickvals: [0, 0.25, 0.5, 0.75, 1],
        ticktext: [0, 0.25, 0.5, 0.75, 1].map(f => (f * roasMax).toFixed(1) + "x"),
      }),
      aspectmode: "cube",
    },
  }, { responsive: true, displaylogo: false });
}

function bubbleChart(divId, data) {
  Plotly.react(divId, [{
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
}

// sortMode: "spend" = keep aggregateJS's spend-descending order as-is (Gamme, Collection).
//           "metric" = re-sort locally by the displayed metric (Coloris, unchanged behaviour).
function barChart(divId, data, metric, ascending, sortMode) {
  let sorted = data.filter(d => d[metric] !== null && d[metric] !== undefined);
  if (sortMode === "metric") {
    sorted = [...sorted].sort((a,b) => ascending ? a[metric]-b[metric] : b[metric]-a[metric]);
  }
  Plotly.react(divId, [{
    type: "bar",
    orientation: "h",
    x: sorted.map(d => d[metric]).reverse(),
    y: sorted.map(d => d.label + `  (${euros(d.spend)}, ${d.n_ads} créas)`).reverse(),
    marker: { color: VIOLET },
  }], {
    margin: {l:260,r:20,t:10,b:50},
    xaxis: { title: metric === "roas" ? "ROAS" : "CPA (€)" },
  }, {responsive:true, displaylogo:false});
}

function prixChart(data) {
  Plotly.react("chart-prix", [
    { type:"bar", name:"ROAS", x: data.map(x=>x.label), y: data.map(x=>x.roas), marker:{color:VIOLET}, yaxis:"y" },
  ], {
    margin: {l:60,r:20,t:10,b:50},
    yaxis: { title: "ROAS" },
    barmode: "group",
  }, {responsive:true, displaylogo:false});
}

function update() {
  const dateRows = rowsInDateRange();
  const rows = filteredRows();

  const start = dateStartEl.value, end = dateEndEl.value;
  document.getElementById("period-label").textContent =
    `Période sélectionnée : ${start} \u2192 ${end} | Persona : ${currentPersona} | (fenêtre glissante disponible : ${DATA.daily.date_min} \u2192 ${DATA.daily.date_max})`;

  renderKPIs(rows);
  marketBarChart(aggregateMarketJS(marketRowsInDateRange()));
  renderPersonaChart(dateRows);
  bubbleChart("chart-format", aggregateJS(rows, "format"));
  barChart("chart-gamme", aggregateJS(rows, "gamme"), "roas", false, "spend");
  barChart("chart-collection", aggregateJS(rows, "collection").slice(0, 12), "cpa", true, "spend");
  barChart("chart-coloris", aggregateJS(rows, "coloris").slice(0, 12), "roas", false, "metric");
  bubbleChart("chart-concept", aggregateJS(rows, "concept").slice(0, 12));
  prixChart(aggregateJS(rows, "prix"));
}

update();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
