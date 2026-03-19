"""
AI pricing engine using Groq API (Llama 3.3 70B).

Takes scraped market data + your properties and produces:
1. Suggested prices for each property
2. Market insights (URGENTE / EVENTO / INFO / OK)
3. City-level market summaries
"""

import json
import logging
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL

logger = logging.getLogger("ai.pricing")


def get_client() -> Groq:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY must be set in .env")
    return Groq(api_key=GROQ_API_KEY)


def compute_suggested_prices(
    properties: list[dict],
    market_comps: list[dict],
    settings: dict,
) -> list[dict]:
    """
    Use Groq LLM to analyze market comps and compute suggested prices
    for each managed property.

    Returns list of {property_id, suggested_price, demand_score, reasoning}.
    """
    client = get_client()

    # Build context for the LLM
    props_summary = []
    for p in properties:
        props_summary.append({
            "id": p["id"],
            "name": p["name"],
            "city": p["city"],
            "region": p["region"],
            "type": p.get("type", ""),
            "platform": p["platform"],
            "current_price": p["current_price"],
        })

    # Group comps by city — limit to top 5 per city to stay within token limits
    comps_by_city = {}
    for c in market_comps:
        city = c["city"]
        if city not in comps_by_city:
            comps_by_city[city] = []
        comps_by_city[city].append({
            "name": c["name"],
            "price": c["price"],
            "rating": c.get("rating"),
            "platform": c["platform"],
        })
    # Keep only top 5 per city (sorted by price) + avg to reduce token count
    for city in comps_by_city:
        listings = comps_by_city[city]
        avg = int(sum(l["price"] for l in listings) / len(listings))
        comps_by_city[city] = sorted(listings, key=lambda x: x["price"])[:5]
        comps_by_city[city].append({"_avg_price": avg, "_count": len(listings)})

    prompt = f"""You are PriceIQ, an AI pricing engine for Italian short-term rental properties.

Analyze the market data below and suggest optimal nightly prices for each managed property.

## Pricing Rules
- Price floor: €{settings.get('price_floor', 60)} (never suggest below this)
- Price ceiling: €{settings.get('price_ceiling', 1200)} (never suggest above this)
- Target undercut: {settings.get('undercut_pct', 4)}% below market average (to stay competitive)
- Weekend premium: {settings.get('weekend_premium_pct', 20)}% (already factored into base suggestion)

## Your Managed Properties
{json.dumps(props_summary, indent=2)}

## Market Competitors by City
{json.dumps(comps_by_city, indent=2)}

## Instructions
For EACH property, analyze comparable listings in the same city and:
1. Calculate the market average price for similar properties
2. Suggest an optimal price that is competitive but maximizes revenue
3. Estimate a demand score (0-100) based on how many comps exist and their occupancy/ratings
4. Provide brief reasoning

Return ONLY valid JSON array, no markdown, no explanation outside the JSON:
[
  {{
    "property_id": 1,
    "suggested_price": 172,
    "market_price": 178,
    "demand_score": 88,
    "reasoning": "Brief explanation in Italian"
  }}
]
"""

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are a JSON-only pricing engine. Return only valid JSON arrays. No markdown fences, no extra text."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=4000,
        )

        text = response.choices[0].message.content.strip()

        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        suggestions = json.loads(text)
        logger.info(f"AI generated {len(suggestions)} price suggestions")
        return suggestions

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response as JSON: {e}")
        logger.error(f"Raw response: {text[:500]}")
        return _fallback_pricing(properties, market_comps, settings)
    except Exception as e:
        logger.error(f"Groq API error: {e}")
        return _fallback_pricing(properties, market_comps, settings)


def _fallback_pricing(properties: list[dict], market_comps: list[dict], settings: dict) -> list[dict]:
    """
    Simple algorithmic fallback if the AI is unavailable.
    Uses market average with undercut percentage.
    """
    undercut = settings.get("undercut_pct", 4) / 100
    floor = settings.get("price_floor", 60)
    ceiling = settings.get("price_ceiling", 1200)

    comps_by_city = {}
    for c in market_comps:
        comps_by_city.setdefault(c["city"], []).append(c["price"])

    results = []
    for p in properties:
        city_prices = comps_by_city.get(p["city"], [])
        if city_prices:
            avg = sum(city_prices) / len(city_prices)
            suggested = int(avg * (1 - undercut))
            demand = min(100, int(len(city_prices) / 50 * 100))
        else:
            suggested = p["current_price"]
            avg = p["current_price"]
            demand = 50

        suggested = max(floor, min(ceiling, suggested))

        results.append({
            "property_id": p["id"],
            "suggested_price": suggested,
            "market_price": int(avg),
            "demand_score": demand,
            "reasoning": "Calcolo algoritmico (fallback)",
        })

    return results


def generate_insights(
    properties: list[dict],
    market_comps: list[dict],
    city_markets: list[dict],
    lang: str = "en",
) -> list[dict]:
    """
    Use Groq LLM to generate actionable insights about the market.
    Returns list of {color, tag, text, sub}.
    """
    client = get_client()

    # Build summary data
    underpriced = [p for p in properties if p.get("suggested_price", 0) > p.get("current_price", 0)]
    underpriced_summary = [
        {"name": p["name"], "city": p["city"], "current": p["current_price"],
         "suggested": p.get("suggested_price", 0), "demand": p.get("demand_score", 0)}
        for p in sorted(underpriced, key=lambda x: x.get("suggested_price", 0) - x["current_price"], reverse=True)[:10]
    ]

    scanned_cities = list({p["city"] for p in properties})
    lang_instruction = "Write all text and sub fields in English." if lang == "en" else "Write all text and sub fields in Italian."

    prompt = f"""You are PriceIQ's insight engine for Italian short-term rentals.

Generate 4-6 actionable insights based on the market data below. Mix of urgency levels.
IMPORTANT: Only reference cities that appear in the data below. The scanned cities are: {', '.join(scanned_cities)}.
Do NOT mention cities that are not in this list.
{lang_instruction}

## Underpriced Properties (biggest gaps)
{json.dumps(underpriced_summary, indent=2)}

## City Market Data
{json.dumps(city_markets, indent=2)}

## Current Date Context
March 2026. Consider upcoming Italian events relevant to the scanned cities only.

## Output Format
Return ONLY valid JSON array:
[
  {{
    "color": "#e05252",
    "tag": "URGENTE",
    "text": "Insight text describing the situation",
    "sub": "Sub-text with details like potential gain or affected cities"
  }}
]

Tag rules:
- URGENTE (color #e05252): Properties significantly underpriced with high demand
- EVENTO (color #d4914a): Upcoming events that should affect pricing
- INFO (color #6a9fd8): Useful market trends or patterns
- OK (color #4caf82): Properties well-positioned, no action needed
"""

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are a JSON-only insight engine. Return only valid JSON arrays. No markdown fences."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
        )

        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        insights = json.loads(text)
        logger.info(f"AI generated {len(insights)} insights")
        return insights

    except Exception as e:
        logger.error(f"Failed to generate insights: {e}")
        return [
            {
                "color": "#6a9fd8",
                "tag": "INFO",
                "text": "Analisi AI temporaneamente non disponibile. Dati di mercato aggiornati con successo.",
                "sub": "I suggerimenti di prezzo sono stati calcolati algoritmicamente",
            }
        ]


def compute_city_markets(market_comps: list[dict], existing_city_markets: list[dict] = None) -> list[dict]:
    """
    Compute city-level market summaries from scraped comps.
    Returns list of city_market dicts ready for upsert.
    """
    from config import CITIES

    # Group comps by city
    by_city = {}
    for c in market_comps:
        by_city.setdefault(c["city"], []).append(c)

    # Build old data lookup for trend calculation
    old_prices = {}
    if existing_city_markets:
        for cm in existing_city_markets:
            old_prices[cm["city"]] = cm.get("avg_price", 0)

    results = []
    for city, config in CITIES.items():
        comps = by_city.get(city, [])
        if not comps:
            continue

        prices = [c["price"] for c in comps if c.get("price")]
        if not prices:
            continue

        avg_price = int(sum(prices) / len(prices))

        # Estimate occupancy from number of high-rated listings
        rated = [c for c in comps if c.get("rating") and c["rating"] >= 4.0]
        occupancy = min(98, int(len(rated) / max(len(comps), 1) * 100))

        # Trend vs previous scan
        old = old_prices.get(city, avg_price)
        trend = round((avg_price - old) / max(old, 1) * 100, 1) if old else 0

        # Season determination (simplified — March 2026)
        coastal = city in ("Amalfi", "Sicilia", "Sardegna")
        if coastal:
            season = "media"  # March is pre-season for coastal
        elif city in ("Venezia", "Firenze", "Roma"):
            season = "alta"  # Spring is high season for art cities
        else:
            season = "media"

        results.append({
            "city": city,
            "region": config["region"],
            "avg_price": avg_price,
            "occupancy": occupancy,
            "trend": trend,
            "season": season,
        })

    return results
