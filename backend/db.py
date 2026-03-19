"""
Supabase database layer for PriceIQ Italia.

Run setup_tables() once to create the schema in your Supabase project,
or create the tables manually via the Supabase SQL editor using the SQL below.
"""

from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY

# ── SQL to run in Supabase SQL Editor (Dashboard > SQL Editor > New Query) ──
SETUP_SQL = """
-- Managed properties
CREATE TABLE IF NOT EXISTS properties (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL,
    region TEXT NOT NULL,
    platform TEXT NOT NULL CHECK (platform IN ('airbnb', 'booking', 'both')),
    current_price INTEGER NOT NULL DEFAULT 0,
    market_price INTEGER NOT NULL DEFAULT 0,
    suggested_price INTEGER NOT NULL DEFAULT 0,
    demand_score INTEGER NOT NULL DEFAULT 0 CHECK (demand_score BETWEEN 0 AND 100),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'applied', 'skip')),
    ai_reasoning TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Scan history
CREATE TABLE IF NOT EXISTS scans (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    cities TEXT[] DEFAULT '{}',
    airbnb_count INTEGER DEFAULT 0,
    booking_count INTEGER DEFAULT 0,
    total_listings INTEGER DEFAULT 0,
    suggestions_count INTEGER DEFAULT 0,
    city_markets_snapshot JSONB DEFAULT '[]',
    insights_snapshot JSONB DEFAULT '[]',
    error_message TEXT DEFAULT ''
);

-- Scraped competitor listings
CREATE TABLE IF NOT EXISTS market_comps (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scan_id BIGINT REFERENCES scans(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    platform TEXT NOT NULL CHECK (platform IN ('airbnb', 'booking', 'both')),
    price INTEGER NOT NULL,
    occupancy TEXT DEFAULT '',
    rating NUMERIC(2,1) DEFAULT 0,
    url TEXT DEFAULT '',
    scraped_at TIMESTAMPTZ DEFAULT NOW()
);

-- City-level market summaries (computed after each scan)
CREATE TABLE IF NOT EXISTS city_markets (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    city TEXT NOT NULL UNIQUE,
    region TEXT NOT NULL,
    avg_price INTEGER NOT NULL DEFAULT 0,
    occupancy INTEGER NOT NULL DEFAULT 0,
    trend NUMERIC(5,1) NOT NULL DEFAULT 0,
    season TEXT NOT NULL DEFAULT 'media' CHECK (season IN ('alta', 'media', 'bassa')),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Price update history log
CREATE TABLE IF NOT EXISTS price_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    property_name TEXT NOT NULL,
    action TEXT NOT NULL,
    price_from INTEGER NOT NULL,
    price_to INTEGER NOT NULL,
    log_type TEXT NOT NULL DEFAULT 'manual' CHECK (log_type IN ('manual', 'auto', 'skip')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- AI-generated insights
CREATE TABLE IF NOT EXISTS insights (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    color TEXT NOT NULL DEFAULT '#6a9fd8',
    tag TEXT NOT NULL DEFAULT 'INFO' CHECK (tag IN ('URGENTE', 'EVENTO', 'INFO', 'OK')),
    text TEXT NOT NULL,
    sub TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Pricing settings
CREATE TABLE IF NOT EXISTS settings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    price_floor INTEGER NOT NULL DEFAULT 60,
    price_ceiling INTEGER NOT NULL DEFAULT 1200,
    undercut_pct INTEGER NOT NULL DEFAULT 4,
    weekend_premium_pct INTEGER NOT NULL DEFAULT 20,
    scan_frequency TEXT NOT NULL DEFAULT '12h',
    auto_mode BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default settings row
INSERT INTO settings (price_floor, price_ceiling, undercut_pct, weekend_premium_pct, scan_frequency, auto_mode)
SELECT 60, 1200, 4, 20, '12h', FALSE
WHERE NOT EXISTS (SELECT 1 FROM settings LIMIT 1);

-- RLS
ALTER TABLE properties ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_comps ENABLE ROW LEVEL SECURITY;
ALTER TABLE city_markets ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE insights ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE scans ENABLE ROW LEVEL SECURITY;

CREATE POLICY IF NOT EXISTS "allow_all" ON properties FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY IF NOT EXISTS "allow_all" ON market_comps FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY IF NOT EXISTS "allow_all" ON city_markets FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY IF NOT EXISTS "allow_all" ON price_log FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY IF NOT EXISTS "allow_all" ON insights FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY IF NOT EXISTS "allow_all" ON settings FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY IF NOT EXISTS "allow_all" ON scans FOR ALL USING (true) WITH CHECK (true);
"""


def get_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


db = get_client()


# ── Properties ──

def get_properties(city: str = None, platform: str = None, status: str = None):
    q = db.table("properties").select("*")
    if city:
        q = q.eq("city", city)
    if platform:
        q = q.eq("platform", platform)
    if status:
        q = q.eq("status", status)
    return q.order("id").execute().data


def upsert_property(prop: dict):
    return db.table("properties").upsert(prop).execute().data


def update_property_status(prop_id: int, status: str, new_price: int = None):
    update = {"status": status, "updated_at": "now()"}
    if new_price is not None:
        update["current_price"] = new_price
    return db.table("properties").update(update).eq("id", prop_id).execute().data


def update_property_prices(prop_id: int, market_price: int, suggested_price: int, demand_score: int, reasoning: str = ""):
    data = {
        "market_price": market_price,
        "suggested_price": suggested_price,
        "demand_score": demand_score,
        "updated_at": "now()",
    }
    if reasoning:
        data["ai_reasoning"] = reasoning
    return db.table("properties").update(data).eq("id", prop_id).execute().data


# ── Scans ──

def create_scan(cities: list[str]) -> dict:
    """Create a new scan record and return it."""
    result = db.table("scans").insert({
        "cities": cities,
        "status": "running",
    }).execute().data
    return result[0] if result else None


def complete_scan(scan_id: int, airbnb_count: int, booking_count: int,
                  total_listings: int, suggestions_count: int,
                  city_markets_snapshot: list, insights_snapshot: list):
    """Mark scan as completed with summary data."""
    import json
    return db.table("scans").update({
        "status": "completed",
        "completed_at": "now()",
        "airbnb_count": airbnb_count,
        "booking_count": booking_count,
        "total_listings": total_listings,
        "suggestions_count": suggestions_count,
        "city_markets_snapshot": json.dumps(city_markets_snapshot),
        "insights_snapshot": json.dumps(insights_snapshot),
    }).eq("id", scan_id).execute().data


def fail_scan(scan_id: int, error: str):
    """Mark scan as failed."""
    return db.table("scans").update({
        "status": "failed",
        "completed_at": "now()",
        "error_message": error[:500],
    }).eq("id", scan_id).execute().data


def get_scans(limit: int = 20):
    """Get scan history, newest first."""
    return db.table("scans").select("*").order("started_at", desc=True).limit(limit).execute().data


def get_scan(scan_id: int):
    """Get a single scan by ID."""
    result = db.table("scans").select("*").eq("id", scan_id).execute().data
    return result[0] if result else None


def get_latest_scan():
    """Get the most recent completed scan."""
    result = db.table("scans").select("*").eq("status", "completed").order("completed_at", desc=True).limit(1).execute().data
    return result[0] if result else None


# ── Market Comps ──

def get_market_comps(city: str = None, scan_id: int = None):
    """Get market comps, optionally filtered by city and/or scan_id."""
    q = db.table("market_comps").select("*")
    if scan_id:
        q = q.eq("scan_id", scan_id)
    if city:
        q = q.eq("city", city)
    return q.order("scraped_at", desc=True).limit(500).execute().data


def get_latest_market_comps(city: str = None):
    """Get comps from the latest completed scan only."""
    latest = get_latest_scan()
    if not latest:
        return []
    return get_market_comps(city=city, scan_id=latest["id"])


def insert_market_comps(listings: list[dict]):
    if not listings:
        return []
    return db.table("market_comps").insert(listings).execute().data


def clear_old_comps(city: str):
    """Remove old comps for a city before inserting fresh ones."""
    return db.table("market_comps").delete().eq("city", city).execute()


# ── City Markets ──

def get_city_markets():
    return db.table("city_markets").select("*").order("avg_price", desc=True).execute().data


def upsert_city_market(data: dict):
    return db.table("city_markets").upsert(data, on_conflict="city").execute().data


# ── Price Log ──

def get_price_log(limit: int = 50):
    return db.table("price_log").select("*").order("created_at", desc=True).limit(limit).execute().data


def insert_log_entry(property_name: str, action: str, price_from: int, price_to: int, log_type: str = "manual"):
    return db.table("price_log").insert({
        "property_name": property_name,
        "action": action,
        "price_from": price_from,
        "price_to": price_to,
        "log_type": log_type,
    }).execute().data


# ── Insights ──

def get_insights():
    return db.table("insights").select("*").order("created_at", desc=True).limit(20).execute().data


def replace_insights(insights: list[dict]):
    """Clear old insights and insert fresh ones from AI analysis."""
    db.table("insights").delete().neq("id", 0).execute()
    if insights:
        return db.table("insights").insert(insights).execute().data
    return []


# ── Settings ──

def get_settings():
    result = db.table("settings").select("*").limit(1).execute().data
    return result[0] if result else None


def update_settings(data: dict):
    data["updated_at"] = "now()"
    settings = get_settings()
    if settings:
        return db.table("settings").update(data).eq("id", settings["id"]).execute().data
    return db.table("settings").insert(data).execute().data
