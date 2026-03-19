"""
Booking.com scraper using Playwright.

Scrapes listing cards from Booking.com search results for Italian cities.
Extracts: name, price per night, rating, location, URL.

Booking.com is slightly easier to scrape than Airbnb because it uses
more semantic HTML with data-testid attributes, but still requires
anti-detection measures for production use.
"""

import asyncio
import random
import re
import logging
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, Page, Browser

from config import (
    SCRAPER_HEADLESS, SCRAPER_TIMEOUT, SCRAPER_DELAY_MIN,
    SCRAPER_DELAY_MAX, MAX_PAGES_PER_CITY, MAX_LISTINGS_PER_CITY,
    PROXY_URL, CITIES,
)

logger = logging.getLogger("scraper.booking")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
]


def _random_delay():
    return random.uniform(SCRAPER_DELAY_MIN, SCRAPER_DELAY_MAX)


def _parse_price(text: str) -> int | None:
    """Extract numeric price from Booking.com price strings."""
    if not text:
        return None
    cleaned = text.replace("\xa0", "").replace(",", "").replace(".", "")
    numbers = re.findall(r"\d+", cleaned)
    if numbers:
        try:
            price = int(numbers[0])
            # Booking sometimes shows total stay price, we want per-night
            # Prices over 5000 are likely multi-night totals
            if price > 5000:
                return None
            return price
        except ValueError:
            return None
    return None


def _parse_rating(text: str) -> float | None:
    """Extract rating from Booking.com score strings like '8.5', 'Scored 9.2'."""
    if not text:
        return None
    match = re.search(r"(\d+\.?\d*)", text)
    if match:
        val = float(match.group(1))
        # Booking uses 0-10 scale, convert to 0-5
        if val > 5:
            return round(val / 2, 1)
        return round(val, 1)
    return None


def _get_search_dates() -> tuple[str, str]:
    """Get check-in (next Friday) and check-out (next Sunday) dates."""
    today = datetime.now()
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    checkin = today + timedelta(days=days_until_friday)
    checkout = checkin + timedelta(days=2)
    return checkin.strftime("%Y-%m-%d"), checkout.strftime("%Y-%m-%d")


async def _extract_listings(page: Page, city: str) -> list[dict]:
    """Extract listing data from the current Booking.com search results page."""
    listings = []

    try:
        await page.wait_for_selector('[data-testid="property-card"], .sr_property_block', timeout=15000)
    except Exception:
        logger.warning(f"No property cards found for {city}")
        return []

    cards = await page.query_selector_all('[data-testid="property-card"]')
    if not cards:
        cards = await page.query_selector_all('.sr_property_block')

    for card in cards:
        try:
            listing = {"city": city, "platform": "booking"}

            # Name
            name_el = await card.query_selector('[data-testid="title"], .sr-hotel__name')
            if name_el:
                listing["name"] = (await name_el.inner_text()).strip()
            else:
                listing["name"] = "Unknown"

            # Price
            price_el = await card.query_selector('[data-testid="price-and-discounted-price"], span[data-testid="price-and-discounted-price"], .bui-price-display__value, [class*="price"]')
            if price_el:
                price_text = await price_el.inner_text()
                listing["price"] = _parse_price(price_text)
            else:
                listing["price"] = None

            # Rating
            rating_el = await card.query_selector('[data-testid="review-score"] div:first-child, .bui-review-score__badge')
            if rating_el:
                rating_text = await rating_el.inner_text()
                listing["rating"] = _parse_rating(rating_text)
            else:
                listing["rating"] = None

            # Review count / occupancy proxy
            review_el = await card.query_selector('[data-testid="review-score"] .a3332d346a, .bui-review-score__text')
            if review_el:
                review_text = await review_el.inner_text()
                listing["review_text"] = review_text.strip()
            else:
                listing["review_text"] = ""

            # URL
            link_el = await card.query_selector('a[data-testid="title-link"], a[href*="/hotel/"]')
            if link_el:
                href = await link_el.get_attribute("href")
                listing["url"] = href or ""
            else:
                listing["url"] = ""

            # Property type
            type_el = await card.query_selector('[data-testid="recommended-units"] span, [data-testid="price-for-x-nights"]')
            if type_el:
                listing["property_type"] = (await type_el.inner_text()).strip()
            else:
                listing["property_type"] = ""

            if listing.get("name") and listing.get("price"):
                listings.append(listing)

        except Exception as e:
            logger.debug(f"Error extracting Booking card: {e}")
            continue

    return listings


async def scrape_city(city: str, browser: Browser) -> list[dict]:
    """Scrape Booking.com listings for a single Italian city."""
    city_config = CITIES.get(city)
    if not city_config:
        logger.error(f"Unknown city: {city}")
        return []

    query = city_config["booking_query"]
    checkin, checkout = _get_search_dates()

    url = (
        f"https://www.booking.com/searchresults.html"
        f"?ss={query}&checkin={checkin}&checkout={checkout}"
        f"&group_adults=2&no_rooms=1&group_children=0"
        f"&selected_currency=EUR&lang=it"
    )

    context = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport={"width": 1366, "height": 768},
        locale="it-IT",
        timezone_id="Europe/Rome",
    )

    # Block heavy resources
    await context.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}", lambda route: route.abort())

    page = await context.new_page()
    all_listings = []

    try:
        for page_num in range(MAX_PAGES_PER_CITY):
            page_url = url if page_num == 0 else f"{url}&offset={page_num * 25}"
            logger.info(f"Scraping Booking.com {city} page {page_num + 1}")

            await page.goto(page_url, wait_until="domcontentloaded", timeout=SCRAPER_TIMEOUT)
            await asyncio.sleep(_random_delay())

            # Dismiss cookie banner
            for popup_sel in [
                'button[id="onetrust-accept-btn-handler"]',
                'button:has-text("Accetta")',
                'button:has-text("Accept")',
                '[aria-label="Dismiss sign-in info."]',
            ]:
                try:
                    popup = await page.query_selector(popup_sel)
                    if popup and await popup.is_visible():
                        await popup.click()
                        await asyncio.sleep(0.5)
                except Exception:
                    pass

            # Scroll to load lazy content
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await asyncio.sleep(0.8)

            listings = await _extract_listings(page, city)
            all_listings.extend(listings)
            logger.info(f"  Found {len(listings)} listings on page {page_num + 1}")

            if len(all_listings) >= MAX_LISTINGS_PER_CITY:
                all_listings = all_listings[:MAX_LISTINGS_PER_CITY]
                break

            # Check for next page
            next_btn = await page.query_selector('button[aria-label="Next page"], button[aria-label="Pagina successiva"]')
            if not next_btn or not await next_btn.is_enabled():
                break

            await asyncio.sleep(_random_delay())

    except Exception as e:
        logger.error(f"Error scraping Booking.com {city}: {e}")
    finally:
        await context.close()

    return all_listings


async def scrape_all_cities(cities: list[str] = None) -> dict[str, list[dict]]:
    """
    Scrape Booking.com for all (or specified) Italian cities.
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
            logger.info(f"Starting Booking.com scrape for {city}...")
            listings = await scrape_city(city, browser)
            results[city] = listings
            logger.info(f"Completed {city}: {len(listings)} listings")

            if city != cities[-1]:
                delay = _random_delay() * 2
                logger.info(f"Waiting {delay:.1f}s before next city...")
                await asyncio.sleep(delay)

        await browser.close()

    total = sum(len(v) for v in results.values())
    logger.info(f"Booking.com scrape complete: {total} listings across {len(results)} cities")
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = asyncio.run(scrape_all_cities(["Roma"]))
    for city, listings in results.items():
        print(f"\n{city}: {len(listings)} listings")
        for l in listings[:3]:
            print(f"  {l['name']} — €{l['price']} — {l.get('rating', 'N/A')}★")
