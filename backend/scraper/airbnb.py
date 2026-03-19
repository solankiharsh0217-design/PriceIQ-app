"""
Airbnb scraper using Playwright.

Scrapes listing cards from Airbnb search results for Italian cities.
Extracts: name, price per night, rating, location, property type, URL.

Important:
- Use residential proxies in production to avoid IP bans.
- Airbnb uses obfuscated CSS classes — we target data-testid attributes
  and structural selectors which are more stable.
- Random delays between requests to mimic human behavior.
"""

import asyncio
import random
import re
import logging
from playwright.async_api import async_playwright, Page, Browser

from config import (
    SCRAPER_HEADLESS, SCRAPER_TIMEOUT, SCRAPER_DELAY_MIN,
    SCRAPER_DELAY_MAX, MAX_PAGES_PER_CITY, MAX_LISTINGS_PER_CITY,
    PROXY_URL, CITIES,
)

logger = logging.getLogger("scraper.airbnb")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
]


def _random_delay():
    return random.uniform(SCRAPER_DELAY_MIN, SCRAPER_DELAY_MAX)


def _parse_price(text: str) -> int | None:
    """Extract numeric price from strings like '€145 per night', '$200', etc."""
    if not text:
        return None
    numbers = re.findall(r"[\d,.]+", text.replace(",", ""))
    if numbers:
        try:
            return int(float(numbers[0]))
        except ValueError:
            return None
    return None


def _parse_rating(text: str) -> float | None:
    """Extract rating from strings like '4.9 (128)', '4.85 out of 5'."""
    if not text:
        return None
    match = re.search(r"(\d+\.?\d*)", text)
    if match:
        val = float(match.group(1))
        if 0 <= val <= 5:
            return round(val, 1)
    return None


async def _extract_listings(page: Page, city: str) -> list[dict]:
    """Extract listing data from the current Airbnb search results page."""
    listings = []

    # Wait for listing cards to render
    try:
        await page.wait_for_selector('[itemprop="itemListElement"], [data-testid="card-container"]', timeout=15000)
    except Exception:
        logger.warning(f"No listing cards found for {city}, page may be blocked or empty")
        return []

    # Try multiple selector strategies (Airbnb changes these)
    cards = await page.query_selector_all('[itemprop="itemListElement"]')
    if not cards:
        cards = await page.query_selector_all('[data-testid="card-container"]')
    if not cards:
        cards = await page.query_selector_all('div[aria-labelledby]')

    for card in cards:
        try:
            listing = {"city": city, "platform": "airbnb"}

            # Name
            name_el = await card.query_selector('[data-testid="listing-card-title"], [id*="title"]')
            if name_el:
                listing["name"] = (await name_el.inner_text()).strip()
            else:
                # Fallback: first prominent text
                name_el = await card.query_selector("div[style*='font-weight'] span, div[role='group'] div")
                listing["name"] = (await name_el.inner_text()).strip() if name_el else "Unknown"

            # Price
            price_el = await card.query_selector('[data-testid="price-availability-row"] span, span:has-text("€"), span:has-text("$")')
            if not price_el:
                price_el = await card.query_selector('span._14y1168, span[class*="price"]')
            if price_el:
                price_text = await price_el.inner_text()
                listing["price"] = _parse_price(price_text)
            else:
                listing["price"] = None

            # Rating
            rating_el = await card.query_selector('[aria-label*="rating"], span:has-text("out of 5"), [class*="rating"]')
            if rating_el:
                rating_text = await rating_el.get_attribute("aria-label") or await rating_el.inner_text()
                listing["rating"] = _parse_rating(rating_text)
            else:
                listing["rating"] = None

            # URL
            link_el = await card.query_selector("a[href*='/rooms/']")
            if link_el:
                href = await link_el.get_attribute("href")
                listing["url"] = f"https://www.airbnb.com{href}" if href and href.startswith("/") else href or ""
            else:
                listing["url"] = ""

            # Property type / subtitle
            subtitle_el = await card.query_selector('[data-testid="listing-card-subtitle"], [id*="subtitle"]')
            if subtitle_el:
                listing["property_type"] = (await subtitle_el.inner_text()).strip()
            else:
                listing["property_type"] = ""

            # Only keep listings with at least a name and price
            if listing.get("name") and listing.get("price"):
                listings.append(listing)

        except Exception as e:
            logger.debug(f"Error extracting card: {e}")
            continue

    return listings


async def scrape_city(city: str, browser: Browser) -> list[dict]:
    """Scrape Airbnb listings for a single Italian city."""
    city_config = CITIES.get(city)
    if not city_config:
        logger.error(f"Unknown city: {city}")
        return []

    query = city_config["airbnb_query"]
    url = f"https://www.airbnb.com/s/{query}/homes"

    context = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport={"width": 1366, "height": 768},
        locale="it-IT",
        timezone_id="Europe/Rome",
    )

    # Block images and fonts to speed up loading
    await context.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}", lambda route: route.abort())

    page = await context.new_page()
    all_listings = []

    try:
        for page_num in range(MAX_PAGES_PER_CITY):
            page_url = url if page_num == 0 else f"{url}?items_offset={page_num * 18}"
            logger.info(f"Scraping Airbnb {city} page {page_num + 1}: {page_url}")

            await page.goto(page_url, wait_until="domcontentloaded", timeout=SCRAPER_TIMEOUT)
            await asyncio.sleep(_random_delay())

            # Close cookie/translation popups
            for popup_selector in [
                'button[data-testid="accept-btn"]',
                '[aria-label="Close"]',
                'button:has-text("OK")',
                'button:has-text("Accetta")',
            ]:
                try:
                    popup = await page.query_selector(popup_selector)
                    if popup and await popup.is_visible():
                        await popup.click()
                        await asyncio.sleep(0.5)
                except Exception:
                    pass

            # Scroll down to trigger lazy-loaded listings
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await asyncio.sleep(0.8)

            listings = await _extract_listings(page, city)
            all_listings.extend(listings)
            logger.info(f"  Found {len(listings)} listings on page {page_num + 1}")

            if len(all_listings) >= MAX_LISTINGS_PER_CITY:
                all_listings = all_listings[:MAX_LISTINGS_PER_CITY]
                break

            # Check if there's a next page
            next_btn = await page.query_selector('a[aria-label="Next"], a[aria-label="Successivo"]')
            if not next_btn:
                break

            await asyncio.sleep(_random_delay())

    except Exception as e:
        logger.error(f"Error scraping Airbnb {city}: {e}")
    finally:
        await context.close()

    return all_listings


async def scrape_all_cities(cities: list[str] = None) -> dict[str, list[dict]]:
    """
    Scrape Airbnb for all (or specified) Italian cities.
    Returns {city_name: [listing_dicts]}.
    """
    if cities is None:
        cities = list(CITIES.keys())

    results = {}

    launch_args = {"headless": SCRAPER_HEADLESS}
    if PROXY_URL:
        launch_args["proxy"] = {"server": PROXY_URL}

    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_args)

        for city in cities:
            logger.info(f"Starting Airbnb scrape for {city}...")
            listings = await scrape_city(city, browser)
            results[city] = listings
            logger.info(f"Completed {city}: {len(listings)} listings")

            # Delay between cities
            if city != cities[-1]:
                delay = _random_delay() * 2
                logger.info(f"Waiting {delay:.1f}s before next city...")
                await asyncio.sleep(delay)

        await browser.close()

    total = sum(len(v) for v in results.values())
    logger.info(f"Airbnb scrape complete: {total} listings across {len(results)} cities")
    return results


# Run standalone for testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = asyncio.run(scrape_all_cities(["Roma"]))
    for city, listings in results.items():
        print(f"\n{city}: {len(listings)} listings")
        for l in listings[:3]:
            print(f"  {l['name']} — €{l['price']} — {l.get('rating', 'N/A')}★")
