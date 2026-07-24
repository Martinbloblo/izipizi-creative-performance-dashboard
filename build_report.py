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
CAMPAIGN_EXT_CSV_PATH = ROOT / "data_market_daily_ext.csv"
FUNNEL_EXT_CSV_PATH = ROOT / "data_funnel_ext.csv"
AD_CAMPAIGN_LINK_CSV_PATH = ROOT / "data_ad_campaign_link.csv"
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


# Looser market extraction for the CPMR chart (section 3), per explicit user
# request: search for the "FR"/"US"/"UK" tokens anywhere in the campaign name,
# regardless of position/delimiter, instead of relying on the "(XX)" paren
# convention used by parse_market() above. Word-boundary regex avoids false
# positives such as "AUSTRALIE" (contains the substring "US") or "OUKA".
_LOOSE_MARKET_RE = {code: re.compile(rf"\b{code}\b") for code in ("FR", "US", "UK")}


def parse_market_loose(campaign_name):
    upper = campaign_name.upper()
    for code in ("FR", "US", "UK"):
        if _LOOSE_MARKET_RE[code].search(upper):
            return code
    return None


def is_whitelisting(campaign_name):
    return "whitelisting" in campaign_name.lower()


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


def load_funnel_ext_rows():
    """LP Views + Initiate Checkout per (date, campaign_name), from
    data_funnel_ext.csv - merged into load_campaign_daily_ext_rows() below to
    feed the Vue Funnel complet section."""
    lookup = {}
    with open(FUNNEL_EXT_CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            lookup[(r["date"], r["campaign_name"])] = {
                "landing_page_views": safe_float(r["landing_page_views"]),
                "initiate_checkout": safe_float(r["initiate_checkout"]),
            }
    return lookup


def load_campaign_daily_ext_rows():
    """Per-campaign, per-day rows with extended metrics (data_market_daily_ext.csv):
    impressions, clicks, CPM, Frequency, add-to-cart, on top of cost/purchases/
    conv_value - used by sections 1 (Resume compte), 3 (CPMR), 4 (Whitelisting)
    and 6 (Comparaison campagne). Also merges in LP Views + Initiate Checkout
    (data_funnel_ext.csv) for Vue Funnel complet."""
    funnel_lookup = load_funnel_ext_rows()
    rows = []
    with open(CAMPAIGN_EXT_CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            funnel = funnel_lookup.get((r["date"], r["campaign_name"]), {})
            rows.append({
                "date": r["date"],
                "campaign_name": r["campaign_name"],
                "cost": safe_float(r["cost"]),
                "purchases": safe_float(r["purchases"]),
                "conv_value": safe_float(r["conv_value"]),
                "impressions": safe_float(r["impressions"]),
                "clicks": safe_float(r["clicks"]),
                "add_to_cart": safe_float(r["add_to_cart"]),
                "frequency": safe_float(r["frequency"]),
                "market_loose": parse_market_loose(r["campaign_name"]),
                "market_full": parse_market(r["campaign_name"]),
                "whitelisting": is_whitelisting(r["campaign_name"]),
                "landing_page_views": funnel.get("landing_page_views", 0.0),
                "initiate_checkout": funnel.get("initiate_checkout", 0.0),
            })
    return rows


def build_campaign_daily_payload():
    rows = load_campaign_daily_ext_rows()
    campaign_names = sorted({r["campaign_name"] for r in rows})
    campaign_index = {name: i for i, name in enumerate(campaign_names)}
    dates = sorted({r["date"] for r in rows})
    markets_full = sorted({r["market_full"] for r in rows if r["market_full"]})
    compact_rows = [
        [
            r["date"], campaign_index[r["campaign_name"]], round(r["cost"], 2),
            round(r["purchases"], 1), round(r["conv_value"], 2),
            round(r["impressions"], 0), round(r["clicks"], 0),
            round(r["add_to_cart"], 1), round(r["frequency"], 4),
            r["market_loose"], 1 if r["whitelisting"] else 0,
            r["market_full"] or "",
            round(r["landing_page_views"], 0), round(r["initiate_checkout"], 0),
        ]
        for r in rows
    ]
    return {
        "campaign_names": campaign_names,
        "rows": compact_rows,
        "date_min": dates[0] if dates else None,
        "date_max": dates[-1] if dates else None,
        "markets_full": markets_full,
    }


# Macro format grouping for the Synthese creative section (Video/Image/
# Carousel mix) - buckets the existing fine-grained FORMAT_RULES labels.
FORMAT_MACRO_MAP = {
    "Video Social Friendly": "Video", "Video UGC": "Video", "Video Brand": "Video",
    "Motion": "Video", "Gif": "Video", "Video": "Video",
    "Image": "Image", "Image Collection": "Image",
    "Carrousel": "Carousel", "Carrousel DAd": "Carousel",
}


def format_macro(label):
    return FORMAT_MACRO_MAP.get(label)


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
    campaign_daily = build_campaign_daily_payload()

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
        "campaign_daily": campaign_daily,
        "format_macro_map": FORMAT_MACRO_MAP,
    }

    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    OUT_PATH.write_text(html, encoding="utf-8")
    print(
        f"Wrote {OUT_PATH} ({len(rows)} ads since Jan 1, spend={fmt_eur(total_spend)}, "
        f"ROAS moyen={avg_roas:.2f}x | daily window {daily['date_min']} -> {daily['date_max']}, "
        f"{len(daily['rows'])} rows, {len(daily['ad_names'])} ads | "
        f"market: {len(market_agg)} markets, {len(market_daily['rows'])} daily rows | "
        f"campaign_daily: {len(campaign_daily['campaign_names'])} campaigns, "
        f"{len(campaign_daily['rows'])} rows)"
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
  .section-eyebrow { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: var(--violet); margin-bottom: 6px; }
  .cmp-select { border: 1px solid #ddd; border-radius: 8px; padding: 6px 10px; font-size: 13px; color: var(--dark); background: #fff; max-width: 100%; }
  .chart { width: 100%; height: 460px; }
  .reco { margin-top: 14px; padding: 14px 18px; background: #F1EEFF; border-left: 4px solid var(--violet); border-radius: 6px; font-size: 14px; line-height: 1.5; }
  .reco b { color: var(--violet); }
  .reco-caption { font-size: 11px; color: #999; margin-top: 8px; font-style: italic; }
  .ideas { margin-top: 10px; padding: 14px 18px; background: #FAFAFA; border-left: 4px solid var(--dark); border-radius: 6px; font-size: 14px; line-height: 1.6; }
  .ideas b { color: var(--dark); }
  .ideas ul { margin: 4px 0 0 0; padding-left: 18px; }
  .ideas-title { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #888; font-weight: 700; }
  footer { text-align: center; color: #999; font-size: 12px; padding: 20px; }

  .kpis-compare { display: flex; gap: 16px; flex-wrap: wrap; }
  .kpi-compare { background: #fff; border: 1px solid #eee; border-radius: 10px; padding: 16px 20px; min-width: 190px; flex: 1 1 190px; }
  .kpi-compare .label { font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: .04em; }
  .kpi-compare .value { font-size: 24px; font-weight: 700; color: var(--violet); margin-top: 4px; }
  .kpi-compare .delta { font-size: 13px; margin-top: 6px; font-weight: 600; }
  .kpi-compare .delta.up { color: #1E9E4E; }
  .kpi-compare .delta.down { color: var(--red); }
  .kpi-compare .delta.na { color: #aaa; font-weight: 400; }
  .kpi-compare .prev-label { font-size: 11px; color: #aaa; margin-top: 2px; }

  .badges-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 18px; margin-top: 18px; }
  .badge-col-title { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #888; font-weight: 700; margin-bottom: 8px; }
  .badge-pill { display: inline-block; background: #F1EEFF; color: var(--violet); border-radius: 14px; padding: 4px 12px; font-size: 12.5px; margin: 0 6px 6px 0; font-weight: 600; }
  .badge-pill .n { color: #888; font-weight: 400; }

  .period-picker { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
  .period-picker .tag { font-weight: 700; font-size: 13px; padding: 3px 10px; border-radius: 6px; color: #fff; }
  .period-picker .tag.a { background: var(--violet); }
  .period-picker .tag.b { background: var(--dark); }

  .granularity-toggle { display: flex; gap: 8px; margin-bottom: 12px; }

  table.cmp-table { width: 100%; border-collapse: collapse; font-size: 12.5px; margin-top: 8px; }
  table.cmp-table th, table.cmp-table td { padding: 8px 10px; border-bottom: 1px solid #eee; text-align: right; white-space: nowrap; }
  table.cmp-table th:first-child, table.cmp-table td:first-child { text-align: left; white-space: normal; max-width: 240px; }
  table.cmp-table th { color: #888; font-size: 11px; text-transform: uppercase; letter-spacing: .03em; background: #FAFAFA; position: sticky; top: 0; }
  table.cmp-table tbody tr:hover { background: #FAFAFA; }
  .cmp-table .up { color: #1E9E4E; }
  .cmp-table .down { color: var(--red); }
  .table-scroll { overflow-x: auto; }

  .empty-state { padding: 30px; text-align: center; color: #999; font-size: 14px; background: #FAFAFA; border-radius: 8px; }
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

<main>

  <section class="card">
    <div class="section-eyebrow">1 &middot; Vue d'ensemble</div>
    <h2>Résumé compte</h2>
    <div class="sub">Spend, Valeur de conversion, Clics, Achats, ROAS sur la période sélectionnée (filtre ci-dessus), comparés à la période N-1 (même durée, immédiatement précédente).</div>
    <div class="kpis-compare" id="kpis-compare"></div>
    <div class="reco-caption" id="resume-caption"></div>
  </section>

  <section class="card">
    <div class="section-eyebrow">2 &middot; Vue d'ensemble</div>
    <h2>Synthèse créative</h2>
    <div class="sub">Mix de formats (spend), sur la période et le persona sélectionnés. Top 3 par catégorie.</div>
    <div id="chart-format-mix" class="chart" style="height:150px"></div>
    <div class="badges-grid" id="top5-badges"></div>
    <div class="reco-caption">"Top produits" = Gamme (SUN, KIDS, READING...). "Top angles" = Collection/Ligne créative, faute de segment "angle" dédié dans la nomenclature.</div>
  </section>

  <section class="card">
    <h2>Vue Marché</h2>
    <div class="sub">Spend x ROAS par marché (FR, US, UK...), extrait de la nomenclature de campagne - triée par spend.</div>
    <div id="chart-market" class="chart"></div>
    <div class="reco" id="reco-market"></div>
    <div class="ideas" id="ideas-market"></div>
    <div class="reco-caption">Recommandation et idées basées sur la période complète (01/01 &rarr; aujourd'hui) - ne varient pas avec les filtres ci-dessus.</div>
  </section>

  <section class="card">
    <div class="section-eyebrow">4 &middot; Analyse temporelle</div>
    <h2>CPMR (CPM x Fréquence) &amp; CPA dans le temps</h2>
    <div class="sub">Sélectionnez un pays (détection large dans le nom de campagne) et/ou une campagne précise pour affiner l'analyse. Barres CPMR (axe principal), courbe CPA en superposition (axe secondaire).</div>
    <div style="display:flex; gap:20px; flex-wrap:wrap; align-items:center; margin-bottom:12px;">
      <div class="granularity-toggle" style="margin-bottom:0;">
        <button class="preset-btn active" data-gran="day">Jour</button>
        <button class="preset-btn" data-gran="week">Semaine</button>
      </div>
      <div class="granularity-toggle" id="cpmr-country-toggle" style="margin-bottom:0;">
        <button class="preset-btn active" data-country="ALL">Tous pays</button>
        <button class="preset-btn" data-country="FR">FR</button>
        <button class="preset-btn" data-country="US">US</button>
        <button class="preset-btn" data-country="UK">UK</button>
      </div>
      <select id="cpmr-campaign-select" class="cmp-select"></select>
    </div>
    <div id="chart-cpmr" class="chart"></div>
    <div class="reco-caption" id="cpmr-mode-caption"></div>
    <div class="reco-caption">CPM et CPA recalculés à partir de Cost/Impressions/Achats (agrégation exacte). Fréquence agrégée en moyenne pondérée par les impressions (approximation usuelle en l'absence de la métrique Reach).</div>
  </section>

  <section class="card">
    <div class="section-eyebrow">5 &middot; Analyse temporelle</div>
    <h2>Vue Tunnel</h2>
    <div class="sub">Vue globale (toutes campagnes), agrégée par mois par défaut - basculez sur semaine ou jour. Filtre marché optionnel.</div>
    <div style="display:flex; gap:20px; flex-wrap:wrap; align-items:center; margin-bottom:12px;">
      <div class="granularity-toggle" id="tunnel-granularity-toggle" style="margin-bottom:0;">
        <button class="preset-btn active" data-gran="month">Mois</button>
        <button class="preset-btn" data-gran="week">Semaine</button>
        <button class="preset-btn" data-gran="day">Jour</button>
      </div>
      <select id="tunnel-market-select" class="cmp-select"></select>
    </div>
    <div class="table-scroll"><table class="cmp-table" id="tunnel-table"></table></div>
  </section>

  <section class="card">
    <div class="section-eyebrow">6 &middot; Analyse temporelle</div>
    <h2>Vue Funnel complet</h2>
    <div class="sub">Vue globale (toutes campagnes), agrégée par mois par défaut - basculez sur semaine ou jour. Filtre marché optionnel.</div>
    <div style="display:flex; gap:20px; flex-wrap:wrap; align-items:center; margin-bottom:12px;">
      <div class="granularity-toggle" id="funnel-granularity-toggle" style="margin-bottom:0;">
        <button class="preset-btn active" data-gran="month">Mois</button>
        <button class="preset-btn" data-gran="week">Semaine</button>
        <button class="preset-btn" data-gran="day">Jour</button>
      </div>
      <select id="funnel-market-select" class="cmp-select"></select>
    </div>
    <div id="funnel-box"></div>
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

  <section class="card">
    <div class="section-eyebrow">7 &middot; Analyse temporelle</div>
    <h2>Whitelisting vs total</h2>
    <div class="sub">% du spend des campagnes "whitelisting" (détection insensible à la casse dans le nom de campagne) vs spend total, sur la période sélectionnée.</div>
    <div id="whitelisting-box"></div>
  </section>

  <section class="card">
    <div class="section-eyebrow">8 &middot; Analyse temporelle</div>
    <h2>Spend par landing page</h2>
    <div class="sub">Agrégation du spend par landing page (destination URL), sur la période sélectionnée.</div>
    <div id="landing-page-box"></div>
  </section>

  <section class="card">
    <div class="section-eyebrow">9 &middot; Analyse temporelle</div>
    <h2>Comparaison campagne (période personnalisée)</h2>
    <div class="sub">2 périodes libres et indépendantes - Impressions, Clics, CTR, Add to cart, Taux d'ATC, Achats, Valeur de conversion, ROAS par campagne.</div>
    <div class="period-picker">
      <span class="tag a">Période A</span>
      <input type="date" id="cmp-a-start"><span>&rarr;</span><input type="date" id="cmp-a-end">
      <span class="tag b" style="margin-left:18px">Période B</span>
      <input type="date" id="cmp-b-start"><span>&rarr;</span><input type="date" id="cmp-b-end">
    </div>
    <div style="margin:14px 0 4px;">
      <label style="font-size:13px; color:#888; margin-right:8px;">Filtrer par marché</label>
      <select id="cmp-market-filter" class="cmp-select"></select>
    </div>
    <div class="table-scroll"><table class="cmp-table" id="cmp-table"></table></div>
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

// Campaign-level rows (extended metrics): [date, campaign_idx, cost, purchases,
// conv_value, impressions, clicks, add_to_cart, frequency, market_loose, whitelisting, market_full]
const FC = { date:0, campaign_idx:1, cost:2, purchases:3, conv_value:4, impressions:5, clicks:6, add_to_cart:7, frequency:8, market_loose:9, whitelisting:10, market_full:11 };
const CAMPAIGN_RAW = DATA.campaign_daily.rows;
const CAMPAIGN_NAMES = DATA.campaign_daily.campaign_names;
const MARKETS_FULL = DATA.campaign_daily.markets_full;
// campaign_idx -> market_full lookup, built once from the raw rows (market is
// constant per campaign, so the first row seen for each campaign_idx suffices).
const CAMPAIGN_MARKET = new Map();
for (const r of CAMPAIGN_RAW) {
  if (!CAMPAIGN_MARKET.has(r[FC.campaign_idx])) CAMPAIGN_MARKET.set(r[FC.campaign_idx], r[FC.market_full]);
}

function euros(x) { return x.toLocaleString('fr-FR', {maximumFractionDigits:0}) + " €"; }
function intFr(x) { return Math.round(x).toLocaleString('fr-FR'); }

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

// ---------------------------------------------------------------------------
// Section 1 - Résumé compte : global account KPIs (Spend/Clics/Achats/ROAS)
// on the shared date filter above, vs an auto-computed N-1 period (same
// duration, immediately preceding). Deliberately account-wide (all campaigns,
// not filtered by the persona pill, which only applies to the creative
// sections below).
// ---------------------------------------------------------------------------
function campaignRowsInRange(start, end) {
  return CAMPAIGN_RAW.filter(r => r[FC.date] >= start && r[FC.date] <= end);
}

function accountAgg(rows) {
  let spend = 0, clicks = 0, purchases = 0, value = 0;
  for (const r of rows) {
    spend += r[FC.cost]; clicks += r[FC.clicks]; purchases += r[FC.purchases]; value += r[FC.conv_value];
  }
  return { spend, clicks, purchases, conv_value: value, roas: spend > 0 ? value / spend : 0 };
}

// N-1 = same duration, immediately preceding the selected period. Clamped to
// the embedded data window's start (data_min); if the full N-1 period falls
// entirely before that window, comparison is unavailable (shown as N/A rather
// than fabricated/zero).
function prevPeriodRange(start, end) {
  const s = new Date(start + "T00:00:00Z"), e = new Date(end + "T00:00:00Z");
  const days = Math.round((e - s) / 86400000) + 1;
  const prevEnd = new Date(s.getTime() - 86400000);
  const prevStart = new Date(prevEnd.getTime() - (days - 1) * 86400000);
  const minDate = new Date(DATA.campaign_daily.date_min + "T00:00:00Z");
  if (prevEnd < minDate) return { start: null, end: null, valid: false };
  const clampedStart = prevStart < minDate ? minDate : prevStart;
  return {
    start: clampedStart.toISOString().slice(0, 10),
    end: prevEnd.toISOString().slice(0, 10),
    valid: prevStart >= minDate,
  };
}

function deltaBlock(curVal, prevVal, fmt) {
  if (prevVal === null || prevVal === undefined) {
    return '<div class="delta na">N-1 indisponible</div>';
  }
  const diff = curVal - prevVal;
  const pct = prevVal !== 0 ? (diff / prevVal * 100) : (curVal > 0 ? 100 : 0);
  const cls = diff >= 0 ? "up" : "down";
  const sign = diff >= 0 ? "+" : "";
  return `<div class="delta ${cls}">${sign}${fmt(diff)} (${sign}${pct.toFixed(1)}%)</div>`;
}

function renderKpisCompare() {
  const start = dateStartEl.value, end = dateEndEl.value;
  const cur = accountAgg(campaignRowsInRange(start, end));
  const prevRange = prevPeriodRange(start, end);
  const prev = prevRange.start ? accountAgg(campaignRowsInRange(prevRange.start, prevRange.end)) : null;

  const metrics = [
    ["Spend", cur.spend, prev ? prev.spend : null, euros],
    ["Valeur de conversion", cur.conv_value, prev ? prev.conv_value : null, euros],
    ["Clics", cur.clicks, prev ? prev.clicks : null, intFr],
    ["Achats", cur.purchases, prev ? prev.purchases : null, intFr],
    ["ROAS", cur.roas, prev ? prev.roas : null, x => x.toFixed(2) + "x"],
  ];
  document.getElementById("kpis-compare").innerHTML = metrics.map(([label, curV, prevV, fmt]) => `
    <div class="kpi-compare">
      <div class="label">${label}</div>
      <div class="value">${fmt(curV)}</div>
      ${deltaBlock(curV, prevV, fmt)}
    </div>`).join("");

  const caption = document.getElementById("resume-caption");
  if (prevRange.valid) {
    caption.textContent = `Période N-1 : ${prevRange.start} \u2192 ${prevRange.end} (même durée, immédiatement précédente).`;
  } else if (prevRange.start) {
    caption.textContent = `Période N-1 tronquée par la fenêtre de données embarquée (disponible à partir du ${DATA.campaign_daily.date_min}) : ${prevRange.start} \u2192 ${prevRange.end}.`;
  } else {
    caption.textContent = `Période N-1 indisponible : entièrement hors de la fenêtre de données embarquée (à partir du ${DATA.campaign_daily.date_min}).`;
  }
}

// ---------------------------------------------------------------------------
// Section 2 - Synthèse créative : format mix (spend, macro-grouped Video/
// Image/Carousel via DATA.format_macro_map) + ad volume by fine-grained
// format, + top 5 badges per category (ad-level data, respects date+persona
// filters like the other creative sections).
// ---------------------------------------------------------------------------
function renderFormatMix(rows) {
  const buckets = new Map();
  let total = 0;
  for (const r of rows) {
    const fmt = r[F.format];
    const macro = fmt && DATA.format_macro_map[fmt];
    if (!macro) continue;
    buckets.set(macro, (buckets.get(macro) || 0) + r[F.cost]);
    total += r[F.cost];
  }
  const order = ["Video", "Image", "Carousel"];
  const colors = { Video: VIOLET, Image: DARK, Carousel: "#FFA733" };
  if (total <= 0) { Plotly.react("chart-format-mix", [], {}); return; }
  const traces = order.filter(o => buckets.has(o)).map(o => ({
    type: "bar", orientation: "h", name: o,
    x: [buckets.get(o)], y: ["Mix"],
    marker: { color: colors[o] },
    text: [`${o} : ${(buckets.get(o) / total * 100).toFixed(0)}% (${euros(buckets.get(o))})`],
    textposition: "inside", hoverinfo: "text",
  }));
  Plotly.react("chart-format-mix", traces, {
    barmode: "stack", margin: { l: 60, r: 20, t: 10, b: 30 },
    xaxis: { visible: false }, showlegend: true, legend: { orientation: "h", y: -0.4 },
  }, { responsive: true, displaylogo: false });
}

// "Top angles"/"Top produits" have no dedicated nomenclature segment - mapped
// to the closest existing fields (collection / gamme respectively), disclosed
// via the section's caption.
const TOP_BADGES_CAP = 3;

function renderTop5Badges(rows) {
  const cats = [
    ["Top personas", "persona"], ["Top formats", "format"], ["Top concepts", "concept"],
    ["Top produits", "gamme"], ["Top angles", "collection"],
  ];
  document.getElementById("top5-badges").innerHTML = cats.map(([title, field]) => {
    const top = aggregateJS(rows, field).slice(0, TOP_BADGES_CAP);
    const pills = top.map(d => `<span class="badge-pill">${d.label} <span class="n">${d.roas.toFixed(2)}x</span></span>`).join("");
    return `<div><div class="badge-col-title">${title}</div>${pills || '<span class="n">—</span>'}</div>`;
  }).join("");
}

// ---------------------------------------------------------------------------
// Section 3 - CPMR (CPM x Fréquence) + CPA overlay, FR/US/UK, day/week toggle.
// CPM and CPA are recomputed from additive raw sums (cost/impressions/
// purchases) so grouping across campaigns/days is mathematically exact.
// Frequency has no additive raw equivalent available (would need Reach), so
// it's combined via an impression-weighted average - a standard, documented
// approximation, not a fabricated number.
// ---------------------------------------------------------------------------
let cpmrGranularity = "day";
let cpmrCountry = "ALL";
let cpmrCampaignIdx = null; // null = aggregated by country; else drill into one campaign

function cpmrBucketKey(dateStr, granularity) {
  if (granularity === "day") return dateStr;
  const d = new Date(dateStr + "T00:00:00Z");
  const day = d.getUTCDay();
  const diff = day === 0 ? -6 : 1 - day;
  return new Date(d.getTime() + diff * 86400000).toISOString().slice(0, 10);
}

// Aggregated (all campaigns) mode: grouped by market, restricted to the
// selected country ("ALL" keeps FR+US+UK grouped bars, else a single market).
function cpmrBucketAgg(rows, granularity, country) {
  const markets = country === "ALL" ? ["FR", "US", "UK"] : [country];
  const buckets = new Map();
  const bucketSet = new Set();
  for (const r of rows) {
    const mkt = r[FC.market_loose];
    if (!mkt || !markets.includes(mkt)) continue;
    const bKey = cpmrBucketKey(r[FC.date], granularity);
    bucketSet.add(bKey);
    const key = bKey + "|" + mkt;
    if (!buckets.has(key)) buckets.set(key, { cost: 0, impressions: 0, purchases: 0, freqImpSum: 0 });
    const b = buckets.get(key);
    b.cost += r[FC.cost];
    b.impressions += r[FC.impressions];
    b.purchases += r[FC.purchases];
    b.freqImpSum += r[FC.frequency] * r[FC.impressions];
  }
  const buckets_sorted = Array.from(bucketSet).sort();
  const series = {};
  for (const m of markets) {
    series[m] = buckets_sorted.map(bk => {
      const b = buckets.get(bk + "|" + m);
      if (!b || b.impressions <= 0) return null;
      return (b.cost / b.impressions * 1000) * (b.freqImpSum / b.impressions);
    });
  }
  const cpaSeries = buckets_sorted.map(bk => {
    let cost = 0, purchases = 0;
    for (const m of markets) {
      const b = buckets.get(bk + "|" + m);
      if (b) { cost += b.cost; purchases += b.purchases; }
    }
    return purchases > 0 ? cost / purchases : null;
  });
  return { buckets: buckets_sorted, series, cpaSeries };
}

// Single-campaign drill-down mode: one CPMR bar series + one CPA line for the
// selected campaign only, ignoring the country filter (a campaign may or may
// not carry an FR/US/UK token).
function cpmrBucketAggCampaign(rows, granularity, campaignIdx) {
  const buckets = new Map();
  for (const r of rows) {
    if (r[FC.campaign_idx] !== campaignIdx) continue;
    const bKey = cpmrBucketKey(r[FC.date], granularity);
    if (!buckets.has(bKey)) buckets.set(bKey, { cost: 0, impressions: 0, purchases: 0, freqImpSum: 0 });
    const b = buckets.get(bKey);
    b.cost += r[FC.cost];
    b.impressions += r[FC.impressions];
    b.purchases += r[FC.purchases];
    b.freqImpSum += r[FC.frequency] * r[FC.impressions];
  }
  const buckets_sorted = Array.from(buckets.keys()).sort();
  const cpmr = buckets_sorted.map(bk => {
    const b = buckets.get(bk);
    return b.impressions > 0 ? (b.cost / b.impressions * 1000) * (b.freqImpSum / b.impressions) : null;
  });
  const cpa = buckets_sorted.map(bk => {
    const b = buckets.get(bk);
    return b.purchases > 0 ? b.cost / b.purchases : null;
  });
  return { buckets: buckets_sorted, cpmr, cpa };
}

function renderCPMRChart() {
  const rows = campaignRowsInRange(dateStartEl.value, dateEndEl.value);
  const modeCaption = document.getElementById("cpmr-mode-caption");
  const layoutBase = {
    margin: { l: 60, r: 60, t: 10, b: 70 },
    barmode: "group",
    xaxis: { tickangle: -45 },
    yaxis: { title: "CPMR" },
    yaxis2: { title: "CPA (€)", overlaying: "y", side: "right" },
    legend: { orientation: "h", y: -0.35 },
  };

  if (cpmrCampaignIdx !== null) {
    const { buckets, cpmr, cpa } = cpmrBucketAggCampaign(rows, cpmrGranularity, cpmrCampaignIdx);
    if (!buckets.length) {
      Plotly.react("chart-cpmr", [], {});
      modeCaption.textContent = "Aucune donnée pour cette campagne sur la période sélectionnée.";
      return;
    }
    const traces = [
      { type: "bar", name: "CPMR", x: buckets, y: cpmr, marker: { color: VIOLET }, yaxis: "y" },
      { type: "scatter", mode: "lines+markers", name: "CPA", x: buckets, y: cpa, yaxis: "y2", line: { color: "#FFA733", width: 2 } },
    ];
    Plotly.react("chart-cpmr", traces, layoutBase, { responsive: true, displaylogo: false });
    modeCaption.textContent = `Campagne sélectionnée : ${CAMPAIGN_NAMES[cpmrCampaignIdx]} (le filtre pays est ignoré en mode campagne unique).`;
    return;
  }

  const { buckets, series, cpaSeries } = cpmrBucketAgg(rows, cpmrGranularity, cpmrCountry);
  if (!buckets.length) {
    Plotly.react("chart-cpmr", [], {});
    modeCaption.textContent = "Aucune donnée pour ce pays sur la période sélectionnée.";
    return;
  }
  const marketColors = { FR: VIOLET, US: "#FF4444", UK: DARK };
  const marketLabels = { FR: "France", US: "USA", UK: "UK" };
  const activeMarkets = cpmrCountry === "ALL" ? ["FR", "US", "UK"] : [cpmrCountry];
  const traces = activeMarkets.map(m => ({
    type: "bar", name: marketLabels[m], x: buckets, y: series[m], marker: { color: marketColors[m] }, yaxis: "y",
  }));
  traces.push({
    type: "scatter", mode: "lines+markers",
    name: cpmrCountry === "ALL" ? "CPA (FR+US+UK)" : `CPA (${marketLabels[cpmrCountry]})`,
    x: buckets, y: cpaSeries, yaxis: "y2", line: { color: "#FFA733", width: 2 },
  });
  Plotly.react("chart-cpmr", traces, layoutBase, { responsive: true, displaylogo: false });
  modeCaption.textContent = "";
}

document.querySelectorAll(".granularity-toggle .preset-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".granularity-toggle .preset-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    cpmrGranularity = btn.dataset.gran;
    renderCPMRChart();
  });
});

document.querySelectorAll("#cpmr-country-toggle .preset-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#cpmr-country-toggle .preset-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    cpmrCountry = btn.dataset.country;
    renderCPMRChart();
  });
});

(function initCpmrCampaignSelect() {
  const sel = document.getElementById("cpmr-campaign-select");
  sel.innerHTML = '<option value="">Toutes les campagnes</option>' +
    CAMPAIGN_NAMES.map((n, i) => `<option value="${i}">${n}</option>`).join("");
  sel.addEventListener("change", () => {
    cpmrCampaignIdx = sel.value === "" ? null : Number(sel.value);
    renderCPMRChart();
  });
})();

// ---------------------------------------------------------------------------
// Section 5 - Vue Tunnel : agrégation globale (toutes campagnes) du tunnel
// média-achat par mois/semaine/jour, avec filtre marché optionnel. Construite
// entièrement à partir des métriques déjà embarquées (cost/impressions/
// clicks/add_to_cart/purchases/conv_value) - toute la fenêtre de données
// embarquée, indépendamment du filtre de date en haut de page.
// ---------------------------------------------------------------------------
const MONTH_NAMES_FR = ["Janvier","Février","Mars","Avril","Mai","Juin","Juillet","Août","Septembre","Octobre","Novembre","Décembre"];
let tunnelGranularity = "month";
let tunnelMarket = null;

function tunnelBucketKey(dateStr, granularity) {
  if (granularity === "day") return dateStr;
  if (granularity === "week") return cpmrBucketKey(dateStr, "week");
  return dateStr.slice(0, 7);
}

function formatBucketLabel(key, granularity) {
  if (granularity === "month") {
    const [y, m] = key.split("-");
    return `${MONTH_NAMES_FR[Number(m) - 1]} ${y}`;
  }
  const label = new Date(key + "T00:00:00Z").toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" });
  return granularity === "week" ? `Semaine du ${label}` : label;
}

function fmtOrDash(fmt) {
  return v => (v === null || v === undefined || !isFinite(v)) ? "—" : fmt(v);
}
const pctFr = v => v.toFixed(1) + " %";
const roasFmt = v => v.toFixed(2) + "x";

function tunnelBucketAgg(rows, granularity, market) {
  const buckets = new Map();
  for (const r of rows) {
    if (market && r[FC.market_full] !== market) continue;
    const bKey = tunnelBucketKey(r[FC.date], granularity);
    if (!buckets.has(bKey)) buckets.set(bKey, { cost: 0, impressions: 0, clicks: 0, add_to_cart: 0, purchases: 0, conv_value: 0 });
    const b = buckets.get(bKey);
    b.cost += r[FC.cost]; b.impressions += r[FC.impressions]; b.clicks += r[FC.clicks];
    b.add_to_cart += r[FC.add_to_cart]; b.purchases += r[FC.purchases]; b.conv_value += r[FC.conv_value];
  }
  return Array.from(buckets.keys()).sort().reverse().map(k => {
    const b = buckets.get(k);
    return {
      key: k,
      impressions: b.impressions,
      cpm: b.impressions > 0 ? b.cost / b.impressions * 1000 : null,
      clicks: b.clicks,
      ctr: b.impressions > 0 ? b.clicks / b.impressions * 100 : null,
      cpc: b.clicks > 0 ? b.cost / b.clicks : null,
      cost: b.cost,
      add_to_cart: b.add_to_cart,
      cost_per_atc: b.add_to_cart > 0 ? b.cost / b.add_to_cart : null,
      purchases: b.purchases,
      cpa: b.purchases > 0 ? b.cost / b.purchases : null,
      cvr: b.clicks > 0 ? b.purchases / b.clicks * 100 : null,
      conv_value: b.conv_value,
      aov: b.purchases > 0 ? b.conv_value / b.purchases : null,
      roas: b.cost > 0 ? b.conv_value / b.cost : null,
    };
  });
}

const TUNNEL_COLS = [
  ["Impressions", "impressions", fmtOrDash(intFr)],
  ["CPM", "cpm", fmtOrDash(euros)],
  ["Clics", "clicks", fmtOrDash(intFr)],
  ["CTR", "ctr", fmtOrDash(pctFr)],
  ["CPC", "cpc", fmtOrDash(euros)],
  ["Budget", "cost", fmtOrDash(euros)],
  ["ATC", "add_to_cart", fmtOrDash(intFr)],
  ["Coût par ATC", "cost_per_atc", fmtOrDash(euros)],
  ["Achats", "purchases", fmtOrDash(intFr)],
  ["CPA", "cpa", fmtOrDash(euros)],
  ["CVR", "cvr", fmtOrDash(pctFr)],
  ["CA TTC", "conv_value", fmtOrDash(euros)],
  ["AOV", "aov", fmtOrDash(euros)],
  ["ROAS", "roas", fmtOrDash(roasFmt)],
];

function renderTunnelTable() {
  const table = document.getElementById("tunnel-table");
  const buckets = tunnelBucketAgg(CAMPAIGN_RAW, tunnelGranularity, tunnelMarket);
  if (!buckets.length) { table.innerHTML = `<tbody><tr><td class="empty-state">Aucune donnée sur la période embarquée.</td></tr></tbody>`; return; }
  const periodLabel = tunnelGranularity === "month" ? "Mois" : tunnelGranularity === "week" ? "Semaine" : "Jour";
  const thead = `<thead><tr><th>${periodLabel}</th>` + TUNNEL_COLS.map(([label]) => `<th>${label}</th>`).join("") + "</tr></thead>";
  const tbody = "<tbody>" + buckets.map(row => {
    const cells = TUNNEL_COLS.map(([, key, fmt]) => `<td>${fmt(row[key])}</td>`).join("");
    return `<tr><td>${formatBucketLabel(row.key, tunnelGranularity)}</td>${cells}</tr>`;
  }).join("") + "</tbody>";
  table.innerHTML = thead + tbody;
}

document.querySelectorAll("#tunnel-granularity-toggle .preset-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#tunnel-granularity-toggle .preset-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    tunnelGranularity = btn.dataset.gran;
    renderTunnelTable();
  });
});

(function initTunnelMarketSelect() {
  const sel = document.getElementById("tunnel-market-select");
  sel.innerHTML = '<option value="">Tous les marchés</option>' +
    MARKETS_FULL.map(m => `<option value="${m}">${m}</option>`).join("");
  sel.addEventListener("change", () => {
    tunnelMarket = sel.value === "" ? null : sel.value;
    renderTunnelTable();
  });
})();

renderTunnelTable();

// ---------------------------------------------------------------------------
// Section 4 - Whitelisting vs total spend, on the shared date filter. Always
// rendered (0%/empty state included) per explicit user requirement.
// ---------------------------------------------------------------------------
function renderWhitelisting() {
  const rows = campaignRowsInRange(dateStartEl.value, dateEndEl.value);
  let total = 0, wl = 0;
  const wlCampaigns = new Set();
  for (const r of rows) {
    total += r[FC.cost];
    if (r[FC.whitelisting]) { wl += r[FC.cost]; wlCampaigns.add(CAMPAIGN_NAMES[r[FC.campaign_idx]]); }
  }
  const pct = total > 0 ? (wl / total * 100) : 0;
  const box = document.getElementById("whitelisting-box");
  if (wlCampaigns.size === 0) {
    box.innerHTML = `<div class="empty-state">Aucune campagne "whitelisting" détectée sur la période sélectionnée (0% du spend, ${euros(total)} au total).</div>`;
    return;
  }
  box.innerHTML = `
    <div class="kpis-compare">
      <div class="kpi-compare"><div class="label">Spend whitelisting</div><div class="value">${euros(wl)}</div></div>
      <div class="kpi-compare"><div class="label">Spend total</div><div class="value">${euros(total)}</div></div>
      <div class="kpi-compare"><div class="label">% whitelisting</div><div class="value">${pct.toFixed(1)}%</div></div>
    </div>
    <div class="reco-caption">Campagnes détectées : ${Array.from(wlCampaigns).map(n => `<b>${n}</b>`).join(", ")}</div>`;
}

// ---------------------------------------------------------------------------
// Section 5 - Spend par landing page (Destination URL). The Supermetrics
// query for this dimension did not complete in a reasonable time for this
// account (retried with several field candidates); rendered as an honest
// "unavailable" state rather than fabricated numbers.
// ---------------------------------------------------------------------------
function renderLandingPage() {
  document.getElementById("landing-page-box").innerHTML =
    `<div class="empty-state">Donnée "landing page" (Destination URL, Supermetrics) indisponible pour le moment : la requête n'a pas abouti dans un délai raisonnable pour ce compte. Cette section sera peuplée dès que la remontée aboutira (à réessayer via la tâche planifiée).</div>`;
}

// ---------------------------------------------------------------------------
// Section 6 - Comparaison campagne : 2 free/independent date ranges, per
// campaign Impressions/Clics/CTR/ATC/Taux ATC/Achats/Valeur de conversion/
// ROAS with absolute + % delta (A -> B).
// ---------------------------------------------------------------------------
function computeCampaignMetrics(rows) {
  const buckets = new Map();
  for (const r of rows) {
    const idx = r[FC.campaign_idx];
    if (!buckets.has(idx)) buckets.set(idx, { impressions: 0, clicks: 0, purchases: 0, conv_value: 0, add_to_cart: 0, cost: 0 });
    const b = buckets.get(idx);
    b.impressions += r[FC.impressions]; b.clicks += r[FC.clicks]; b.purchases += r[FC.purchases];
    b.conv_value += r[FC.conv_value]; b.add_to_cart += r[FC.add_to_cart]; b.cost += r[FC.cost];
  }
  const out = new Map();
  for (const [idx, b] of buckets) {
    out.set(idx, {
      impressions: b.impressions, clicks: b.clicks,
      ctr: b.impressions > 0 ? b.clicks / b.impressions * 100 : 0,
      add_to_cart: b.add_to_cart,
      taux_atc: b.clicks > 0 ? b.add_to_cart / b.clicks * 100 : 0,
      purchases: b.purchases, conv_value: b.conv_value,
      roas: b.cost > 0 ? b.conv_value / b.cost : 0,
      cost: b.cost,
    });
  }
  return out;
}

const CMP_COLS = [
  ["Impressions", "impressions", intFr],
  ["Clics", "clicks", intFr],
  ["CTR", "ctr", v => v.toFixed(2) + "%"],
  ["Add to cart", "add_to_cart", intFr],
  ["Taux d'ATC", "taux_atc", v => v.toFixed(2) + "%"],
  ["Achats", "purchases", intFr],
  ["Valeur de conversion", "conv_value", euros],
  ["ROAS", "roas", v => v.toFixed(2) + "x"],
];
const CMP_ZERO = { impressions: 0, clicks: 0, ctr: 0, add_to_cart: 0, taux_atc: 0, purchases: 0, conv_value: 0, roas: 0, cost: 0 };

let cmpMarketFilter = null;

function renderComparisonTable() {
  const aStart = document.getElementById("cmp-a-start").value, aEnd = document.getElementById("cmp-a-end").value;
  const bStart = document.getElementById("cmp-b-start").value, bEnd = document.getElementById("cmp-b-end").value;
  const table = document.getElementById("cmp-table");
  if (!aStart || !aEnd || !bStart || !bEnd) { table.innerHTML = ""; return; }

  const metricsA = computeCampaignMetrics(campaignRowsInRange(aStart, aEnd));
  const metricsB = computeCampaignMetrics(campaignRowsInRange(bStart, bEnd));
  let idxList = Array.from(new Set([...metricsA.keys(), ...metricsB.keys()]));
  if (cmpMarketFilter !== null) idxList = idxList.filter(idx => CAMPAIGN_MARKET.get(idx) === cmpMarketFilter);

  const rows = idxList.map(idx => {
    const a = metricsA.get(idx) || CMP_ZERO, b = metricsB.get(idx) || CMP_ZERO;
    return { name: CAMPAIGN_NAMES[idx], a, b, sortKey: Math.max(a.cost, b.cost) };
  }).sort((x, y) => y.sortKey - x.sortKey);

  const thead = "<thead><tr><th>Campagne</th>" +
    CMP_COLS.map(([label]) => `<th>${label}<br><span style="font-weight:400">A &rarr; B (&Delta;%)</span></th>`).join("") +
    "</tr></thead>";
  const tbody = "<tbody>" + rows.map(r => {
    const cells = CMP_COLS.map(([, key, fmt]) => {
      const av = r.a[key], bv = r.b[key];
      const diff = bv - av;
      const pct = av !== 0 ? (diff / av * 100) : (bv > 0 ? 100 : 0);
      const cls = diff >= 0 ? "up" : "down";
      const sign = diff >= 0 ? "+" : "";
      return `<td>${fmt(av)} &rarr; ${fmt(bv)} <span class="${cls}">(${sign}${pct.toFixed(1)}%)</span></td>`;
    }).join("");
    return `<tr><td>${r.name}</td>${cells}</tr>`;
  }).join("") + "</tbody>";

  table.innerHTML = thead + tbody;
}

const cmpAStart = document.getElementById("cmp-a-start"), cmpAEnd = document.getElementById("cmp-a-end");
const cmpBStart = document.getElementById("cmp-b-start"), cmpBEnd = document.getElementById("cmp-b-end");
[cmpAStart, cmpAEnd, cmpBStart, cmpBEnd].forEach(el => {
  el.min = DATA.campaign_daily.date_min; el.max = DATA.campaign_daily.date_max;
});
(function initCmpDefaults() {
  const end = DATA.campaign_daily.date_max;
  const endDate = new Date(end + "T00:00:00Z");
  const aStartDate = new Date(endDate.getTime() - 6 * 86400000);
  const bEndDate = new Date(aStartDate.getTime() - 86400000);
  const bStartDate = new Date(bEndDate.getTime() - 6 * 86400000);
  const minDate = new Date(DATA.campaign_daily.date_min + "T00:00:00Z");
  const clamp = d => (d < minDate ? minDate : d);
  cmpAStart.value = clamp(aStartDate).toISOString().slice(0, 10);
  cmpAEnd.value = end;
  cmpBStart.value = clamp(bStartDate).toISOString().slice(0, 10);
  cmpBEnd.value = bEndDate.toISOString().slice(0, 10);
})();
[cmpAStart, cmpAEnd, cmpBStart, cmpBEnd].forEach(el => el.addEventListener("change", renderComparisonTable));

(function initCmpMarketSelect() {
  const sel = document.getElementById("cmp-market-filter");
  sel.innerHTML = '<option value="">Tous les marchés</option>' +
    MARKETS_FULL.map(m => `<option value="${m}">${m}</option>`).join("");
  sel.addEventListener("change", () => {
    cmpMarketFilter = sel.value === "" ? null : sel.value;
    renderComparisonTable();
  });
})();

function update() {
  const dateRows = rowsInDateRange();
  const rows = filteredRows();

  const start = dateStartEl.value, end = dateEndEl.value;
  document.getElementById("period-label").textContent =
    `Période sélectionnée : ${start} \u2192 ${end} | Persona : ${currentPersona} | (fenêtre glissante disponible : ${DATA.daily.date_min} \u2192 ${DATA.daily.date_max})`;

  renderKpisCompare();
  renderFormatMix(rows);
  renderTop5Badges(rows);
  marketBarChart(aggregateMarketJS(marketRowsInDateRange()));
  renderPersonaChart(dateRows);
  bubbleChart("chart-format", aggregateJS(rows, "format"));
  barChart("chart-gamme", aggregateJS(rows, "gamme"), "roas", false, "spend");
  barChart("chart-collection", aggregateJS(rows, "collection").slice(0, 12), "cpa", true, "spend");
  barChart("chart-coloris", aggregateJS(rows, "coloris").slice(0, 12), "roas", false, "metric");
  bubbleChart("chart-concept", aggregateJS(rows, "concept").slice(0, 12));
  prixChart(aggregateJS(rows, "prix"));
  renderCPMRChart();
  renderWhitelisting();
}

renderLandingPage();
renderComparisonTable();
update();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
