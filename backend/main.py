"""
PriceIQ Italia — FastAPI Backend

Serves the frontend and provides REST API endpoints for:
- Property management (CRUD + apply/skip pricing)
- Market data (scraped competitors, city summaries)
- AI insights
- Triggering market scans with city selection
- Scan history with snapshots
- Settings management
"""

import asyncio
import json
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

import db
from scraper.airbnb import scrape_all_cities as scrape_airbnb
from scraper.booking import scrape_all_cities as scrape_booking
from ai.pricing import compute_suggested_prices, generate_insights, compute_city_markets
from scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("priceiq")

# Track scan state
scan_state = {"running": False, "last_scan": None, "listings_count": 0, "scan_id": None, "cities": [], "platforms": []}


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="PriceIQ Italia", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic Models ──

class ApplyRequest(BaseModel):
    price_override: int | None = None

class SettingsUpdate(BaseModel):
    price_floor: int | None = None
    price_ceiling: int | None = None
    undercut_pct: int | None = None
    weekend_premium_pct: int | None = None
    scan_frequency: str | None = None
    auto_mode: bool | None = None

class PropertyCreate(BaseModel):
    name: str
    type: str = ""
    city: str
    region: str
    platform: str = "both"
    current_price: int = 0

class ScanRequest(BaseModel):
    cities: list[str] | None = None
    platforms: list[str] | None = None  # ["airbnb", "booking"] or subset
    lang: str = "en"  # "en" or "it"


# ── Properties ──

@app.get("/api/properties")
def list_properties(city: str = None, platform: str = None, status: str = None):
    props = db.get_properties(city=city, platform=platform, status=status)
    return {"properties": props, "total": len(props)}


@app.post("/api/properties")
def create_property(data: PropertyCreate):
    prop = db.upsert_property(data.model_dump())
    return {"property": prop}


@app.post("/api/properties/{prop_id}/apply")
def apply_price(prop_id: int, data: ApplyRequest):
    props = db.get_properties()
    prop = next((p for p in props if p["id"] == prop_id), None)
    if not prop:
        raise HTTPException(404, "Property not found")
    if prop["status"] != "pending":
        raise HTTPException(400, "Property is not pending")

    old_price = prop["current_price"]
    new_price = data.price_override if data.price_override else prop["suggested_price"]

    db.update_property_status(prop_id, "applied", new_price)
    db.insert_log_entry(prop["name"], "Applied manually", old_price, new_price, "manual")

    return {"success": True, "old_price": old_price, "new_price": new_price}


@app.post("/api/properties/{prop_id}/skip")
def skip_price(prop_id: int):
    props = db.get_properties()
    prop = next((p for p in props if p["id"] == prop_id), None)
    if not prop:
        raise HTTPException(404, "Property not found")

    db.update_property_status(prop_id, "skip")
    db.insert_log_entry(prop["name"], "Skipped by user", prop["current_price"], prop["suggested_price"], "skip")

    return {"success": True}


@app.post("/api/properties/bulk-apply")
def bulk_apply():
    pending = db.get_properties(status="pending")
    count = 0
    for p in pending:
        old_price = p["current_price"]
        new_price = p["suggested_price"]
        db.update_property_status(p["id"], "applied", new_price)
        db.insert_log_entry(p["name"], "Bulk applied", old_price, new_price, "manual")
        count += 1
    return {"success": True, "applied_count": count}


@app.post("/api/properties/bulk-skip")
def bulk_skip():
    pending = db.get_properties(status="pending")
    count = 0
    for p in pending:
        db.update_property_status(p["id"], "skip")
        count += 1
    return {"success": True, "skipped_count": count}


# ── Market Data ──

@app.get("/api/market")
def get_market(city: str = None, scan_id: int = None):
    """Get market comps. Defaults to latest scan if no scan_id specified."""
    if scan_id:
        comps = db.get_market_comps(city=city, scan_id=scan_id)
    else:
        comps = db.get_latest_market_comps(city=city)
    return {"comps": comps, "total": len(comps)}


@app.get("/api/cities")
def get_cities():
    markets = db.get_city_markets()
    return {"cities": markets}


# ── Insights ──

@app.get("/api/insights")
def get_insights():
    insights = db.get_insights()
    return {"insights": insights}


# ── Log ──

@app.get("/api/log")
def get_log(limit: int = 50):
    log = db.get_price_log(limit=limit)
    return {"log": log}


# ── Settings ──

@app.get("/api/settings")
def get_settings():
    settings = db.get_settings()
    return {"settings": settings}


@app.put("/api/settings")
def update_settings(data: SettingsUpdate):
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(400, "No settings to update")
    result = db.update_settings(update)
    return {"settings": result}


# ── Scan History ──

@app.get("/api/scans")
def list_scans(limit: int = 20):
    """List past scans, newest first."""
    scans = db.get_scans(limit=limit)
    return {"scans": scans, "total": len(scans)}


@app.get("/api/scans/{scan_id}")
def get_scan_detail(scan_id: int):
    """Get full details for a specific scan, including its market comps."""
    scan = db.get_scan(scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")
    comps = db.get_market_comps(scan_id=scan_id)
    return {"scan": scan, "comps": comps, "total_comps": len(comps)}


# ── Scan ──

@app.get("/api/scan/status")
def scan_status():
    return scan_state


@app.post("/api/scan")
async def trigger_scan(background_tasks: BackgroundTasks, data: ScanRequest = None):
    if scan_state["running"]:
        raise HTTPException(409, "A scan is already running")

    cities = data.cities if data and data.cities else None
    platforms = data.platforms if data and data.platforms else None
    lang = data.lang if data else "en"
    background_tasks.add_task(run_scan, cities, platforms, lang)
    return {"message": "Scan started", "status": "running"}


async def run_scan(cities: list[str] = None, platforms: list[str] = None, lang: str = "en"):
    """
    Full scan pipeline:
    1. Create scan record
    2. Scrape selected platforms for selected cities
    3. Store raw comps tagged with scan_id
    4. Run AI pricing analysis (only for scanned cities)
    5. Update properties with suggested prices
    6. Generate insights (only for scanned cities)
    7. Save snapshots to scan record
    """
    scan_state["running"] = True
    logger.info("Starting market scan...")

    from config import CITIES as CITY_CONFIG
    scan_cities = cities or list(CITY_CONFIG.keys())
    scan_platforms = platforms or ["airbnb", "booking"]

    # Create scan record
    scan_record = db.create_scan(scan_cities)
    if not scan_record:
        logger.error("Failed to create scan record")
        scan_state["running"] = False
        return

    scan_id = scan_record["id"]
    scan_state["scan_id"] = scan_id

    try:
        # 1. Scrape selected platforms
        airbnb_results = {}
        booking_results = {}

        if "airbnb" in scan_platforms and "booking" in scan_platforms:
            airbnb_results, booking_results = await asyncio.gather(
                scrape_airbnb(cities), scrape_booking(cities)
            )
        elif "airbnb" in scan_platforms:
            airbnb_results = await scrape_airbnb(cities)
        elif "booking" in scan_platforms:
            booking_results = await scrape_booking(cities)

        # 2. Build comps list tagged with scan_id
        all_comps = []
        airbnb_count = 0
        booking_count = 0

        for city, listings in airbnb_results.items():
            for l in listings:
                comp = {
                    "scan_id": scan_id,
                    "name": l["name"],
                    "city": l["city"],
                    "platform": "airbnb",
                    "price": l["price"],
                    "occupancy": "",
                    "rating": l.get("rating") or 0,
                    "url": l.get("url", ""),
                }
                all_comps.append(comp)
                airbnb_count += 1

        for city, listings in booking_results.items():
            for l in listings:
                comp = {
                    "scan_id": scan_id,
                    "name": l["name"],
                    "city": l["city"],
                    "platform": "booking",
                    "price": l["price"],
                    "occupancy": l.get("review_text", ""),
                    "rating": l.get("rating") or 0,
                    "url": l.get("url", ""),
                }
                all_comps.append(comp)
                booking_count += 1

        if all_comps:
            db.insert_market_comps(all_comps)

        # 3. Compute city market summaries
        existing_city_markets = db.get_city_markets()
        city_markets = compute_city_markets(all_comps, existing_city_markets)
        for cm in city_markets:
            db.upsert_city_market(cm)

        # 4. AI pricing analysis — only for properties in scanned cities
        all_properties = db.get_properties()
        scanned_properties = [p for p in all_properties if p["city"] in scan_cities]
        settings = db.get_settings() or {}

        suggestions = []
        if scanned_properties and all_comps:
            suggestions = compute_suggested_prices(scanned_properties, all_comps, settings)

            for sug in suggestions:
                db.update_property_prices(
                    prop_id=sug["property_id"],
                    market_price=sug.get("market_price", 0),
                    suggested_price=sug["suggested_price"],
                    demand_score=sug.get("demand_score", 50),
                    reasoning=sug.get("reasoning", ""),
                )

        # 5. Reset pending status for scanned properties with new suggestions
        for prop in scanned_properties:
            if prop["status"] != "applied":
                db.update_property_status(prop["id"], "pending")

        # 6. Generate insights — only for scanned cities
        updated_properties = [p for p in db.get_properties() if p["city"] in scan_cities]
        scanned_city_markets = [cm for cm in db.get_city_markets() if cm["city"] in scan_cities]
        insights = generate_insights(updated_properties, all_comps, scanned_city_markets, lang=lang)
        db.replace_insights(insights)

        # 7. Save snapshots to scan record
        db.complete_scan(
            scan_id=scan_id,
            airbnb_count=airbnb_count,
            booking_count=booking_count,
            total_listings=len(all_comps),
            suggestions_count=len(suggestions),
            city_markets_snapshot=scanned_city_markets,
            insights_snapshot=insights,
        )

        # 8. Auto-apply if enabled
        if settings.get("auto_mode"):
            pending = db.get_properties(status="pending")
            for p in pending:
                old_price = p["current_price"]
                new_price = p["suggested_price"]
                db.update_property_status(p["id"], "applied", new_price)
                db.insert_log_entry(p["name"], "Auto-updated", old_price, new_price, "auto")
            logger.info(f"Auto-applied {len(pending)} price updates")

        scan_state["last_scan"] = datetime.now().isoformat()
        scan_state["listings_count"] = len(all_comps)
        scan_state["cities"] = scan_cities
        scan_state["platforms"] = scan_platforms
        logger.info(f"Scan #{scan_id} complete: {len(all_comps)} comps, {len(suggestions)} suggestions")

    except Exception as e:
        logger.error(f"Scan #{scan_id} failed: {e}", exc_info=True)
        db.fail_scan(scan_id, str(e))
    finally:
        scan_state["running"] = False


# ── Serve Frontend ──

@app.get("/")
async def serve_frontend():
    return FileResponse("../index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
