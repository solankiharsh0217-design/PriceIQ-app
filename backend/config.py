import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

# Scraper settings
SCRAPER_HEADLESS = True
SCRAPER_TIMEOUT = 60000  # ms
SCRAPER_DELAY_MIN = 2.0  # seconds between requests
SCRAPER_DELAY_MAX = 5.0
MAX_PAGES_PER_CITY = 3
MAX_LISTINGS_PER_CITY = 50

# Proxy (optional but recommended)
PROXY_URL = os.getenv("PROXY_URL", "")

# Supported cities with search parameters
CITIES = {
    "Roma":     {"airbnb_query": "Rome--Italy", "booking_query": "Rome", "region": "Lazio"},
    "Firenze":  {"airbnb_query": "Florence--Italy", "booking_query": "Florence", "region": "Toscana"},
    "Venezia":  {"airbnb_query": "Venice--Italy", "booking_query": "Venice", "region": "Veneto"},
    "Milano":   {"airbnb_query": "Milan--Italy", "booking_query": "Milan", "region": "Lombardia"},
    "Napoli":   {"airbnb_query": "Naples--Italy", "booking_query": "Naples", "region": "Campania"},
    "Amalfi":   {"airbnb_query": "Amalfi-Coast--Italy", "booking_query": "Amalfi+Coast", "region": "Campania"},
    "Sicilia":  {"airbnb_query": "Sicily--Italy", "booking_query": "Sicily", "region": "Sicilia"},
    "Sardegna": {"airbnb_query": "Sardinia--Italy", "booking_query": "Sardinia", "region": "Sardegna"},
    "Toscana":  {"airbnb_query": "Tuscany--Italy", "booking_query": "Tuscany", "region": "Toscana"},
    "Como":     {"airbnb_query": "Lake-Como--Italy", "booking_query": "Lake+Como", "region": "Lombardia"},
}

# Scan schedule
SCAN_INTERVAL_HOURS = 12
