# PriceIQ Italia — Claude Code Context

> AI-powered property pricing engine for Italian short-term rentals.
> Analyzes Airbnb and Booking.com market data, suggests optimal nightly prices,
> and lets property managers approve or auto-apply suggestions across 25+ properties
> in 10 Italian cities.

---

## Project Structure

```
priceiq-italy/
├── CLAUDE.md                  ← you are here
├── priceiq-italy.html                 ← single-file app (current state, fully functional)
├── README.md
└── .antigravity/
    └── rules.md               ← Antigravity agent rules (mirrors this file)
```

> **Current state:** The entire app lives in `priceiq-italy.html` — one self-contained file
> with inline CSS, HTML, and JavaScript. No build step, no dependencies, no server.
> Open in any browser and it works.

---

## What This App Does

1. **Simulates a market scan** — fetches and displays comparable Airbnb/Booking.com
   listings across 10 Italian cities (data is currently mocked in JS; see the
   `MARKET_COMPS` and `CITY_MARKETS` arrays).
2. **Suggests optimal prices** — each property has a `sug` (suggested) price computed
   from `mkt` (market average) with a configurable undercut percentage.
3. **Lets the manager act** — per-property Apply (with optional price override) or Skip;
   bulk apply all pending; auto-update toggle that marks prices as auto-applied.
4. **Tracks history** — every apply/skip is appended to `LOG_DATA` and shown in the
   Storico (log) page.

---

## Data Model

All data lives in JavaScript arrays at the top of `priceiq-italy.html`. There is no backend or database yet.

### `PROPS` — the 25 managed properties

```js
{
  id:       number,   // unique identifier
  name:     string,   // Italian property name, e.g. "Appartamento Trastevere"
  type:     string,   // Italian property type, e.g. "2 locali · Storico"
  city:     string,   // one of: Roma, Firenze, Venezia, Milano, Napoli,
                      //         Amalfi, Sicilia, Sardegna, Toscana, Como
  region:   string,   // Italian region, e.g. "Lazio", "Toscana", "Veneto"
  platform: string,   // "airbnb" | "booking" | "both"
  cur:      number,   // current nightly price in EUR
  mkt:      number,   // market average nightly price in EUR (from scan)
  sug:      number,   // AI-suggested nightly price in EUR
  demand:   number,   // demand score 0–100 (higher = more bookings in area)
  status:   string,   // "pending" | "applied" | "skip"
}
```

**Pricing logic** (currently hardcoded, configurable in Settings page):
```
sug = mkt * (1 - undercut%) 
    + weekend_premium (Fri–Sun only)
    + seasonal_multiplier (see SEASON_RULES)
```

### `MARKET_COMPS` — competitor listings pulled from scan

```js
{
  name:     string,   // competitor listing name
  city:     string,   // city
  platform: string,   // "airbnb" | "booking" | "both"
  price:    number,   // their nightly price in EUR
  occ:      string,   // occupancy string, e.g. "91%"
  rating:   number,   // star rating, e.g. 4.9
}
```

### `CITY_MARKETS` — city-level market summary

```js
{
  city:     string,
  region:   string,
  avgPrice: number,   // average nightly price across all listings in city (EUR)
  occ:      number,   // average occupancy percentage (0–100)
  trend:    number,   // YoY price change percentage
  season:   string,   // "alta" | "media" | "bassa"
}
```

### `LOG_DATA` — price update history

```js
{
  time:    string,   // human-readable time, e.g. "10:22" or "Ieri"
  prop:    string,   // property name
  action:  string,   // Italian action description
  from:    number,   // old price EUR
  to:      number,   // new price EUR
  type:    string,   // "manual" | "auto" | "skip"
}
```

### `INSIGHTS_DATA` — AI-generated alerts

```js
{
  color:  string,   // hex color for dot indicator
  tag:    string,   // "URGENTE" | "EVENTO" | "INFO" | "OK"
  text:   string,   // Italian insight description
  sub:    string,   // Italian sub-text (e.g. city or gain info)
}
```

---

## App Pages & Navigation

The app has 7 pages rendered via `gotoPage(pageName)`. All content is injected into `<div id="content">`.

| Page name    | Italian label        | Function                                              |
|--------------|----------------------|-------------------------------------------------------|
| `dashboard`  | Panoramica           | Metrics, trend chart, market panel, AI insights       |
| `properties` | Proprietà            | Full table, search/filter, apply/skip per property    |
| `market`     | Mercato              | Competitor listings, demand heatmap, seasonal chart   |
| `analysis`   | Analisi AI           | AI summary, top opportunities, city uplift donut      |
| `log`        | Storico              | Price update history log                              |
| `settings`   | Impostazioni         | Pricing rule sliders, scan frequency, auto toggle     |
| `seasons`    | Stagionalità         | Seasonal multiplier cards, city pricing grid          |

---

## Key Functions

### Navigation & Rendering

```js
gotoPage(pageName)          // renders a page, rebuilds charts with 60ms delay
renderDash()                // returns HTML string for dashboard
renderProps()               // returns HTML string for properties table (paginated)
renderMarket()              // returns HTML string for market page
renderAnalysis()            // returns HTML string for AI analysis page
renderLog()                 // returns HTML string for log page
renderSettings()            // returns HTML string for settings page
renderSeasons()             // returns HTML string for seasonality page
```

### Chart Builders (called after page render)

```js
buildTrend()                // Line chart: your prices vs market (30d), canvas #trendChart
buildCityBar()              // Bar chart: market avg vs your avg by city, canvas #cityChart
buildDemandChart()          // Bar chart: demand by day of week, canvas #demandChart
buildSeasonChart()          // Bar chart: monthly prices coastal vs città d'arte, canvas #seasonChart
buildAnalysisChart()        // Donut chart: pending uplift by city, canvas #analysisChart
```

All charts use **Chart.js 4.4.1** loaded from cdnjs. Stored in `charts` object to allow `destroy()` before rebuild.

### Actions

```js
runScan()                   // animates progress bar, simulates 3.2s scan, calls showNotif()
toggleAuto(el)              // toggles autoMode bool, updates sidebar status
setFilter(type, val)        // sets fCity or fPlatform, re-renders current page
onSearch(v)                 // sets searchQ, resets to page 1, re-renders properties
setTab(t)                   // sets curTab ('all'|'pending'|'applied'|'skip'), re-renders
goPg(p)                     // sets propPage, re-renders properties
openModal(id)               // populates and shows the price confirmation modal
closeModal()                // hides modal overlay
confirmApply()              // applies price (or override), updates prop status, logs entry
skipProp(id)                // sets status to 'skip', updates badge, re-renders
bulkAll()                   // applies all pending props, logs each, updates badge
bulkSkip()                  // skips all pending props, updates badge
showNotif(msg)              // shows bottom-right notification for 3.5s
```

### State Variables

```js
let curPage = 'dashboard'   // active page name
let autoMode = false        // whether auto-update is on
let fCity = 'all'           // city filter
let fPlatform = 'all'       // platform filter
let searchQ = ''            // search string
let curTab = 'all'          // active tab in properties
let propPage = 1            // current pagination page
const PG = 10               // properties per page
let selProp = null          // currently selected property in modal
let charts = {}             // chart instances keyed by name
```

---

## Design System

The app uses a **warm dark Italian luxury** aesthetic — terracotta golds on near-black.

### Color Palette (CSS variables)

```css
--bg:      #0e0c0a    /* page background */
--bg2:     #151210    /* sidebar, panels */
--bg3:     #1e1a16    /* inputs, cards */
--bg4:     #27221c    /* subtle fills */
--bg5:     #312b23    /* borders, toggles */
--text:    #f5ede0    /* primary text */
--text2:   #a09070    /* secondary text */
--text3:   #5c5040    /* muted text, labels */
--gold:    #c9973a    /* primary accent — CTAs, active nav, suggested prices */
--gold2:   #e8c06a    /* lighter gold — hover, gradient end */
--green:   #4caf82    /* success, applied, gains */
--red:     #e05252    /* urgent, danger, losses */
--amber:   #d4914a    /* warnings, events */
--blue:    #6a9fd8    /* info, informational insights */
```

### Typography

```
--font-display: 'Cormorant Garamond', serif   → page titles, modal titles
--font-mono:    'DM Mono', monospace          → prices, scores, codes
--font-body:    'Figtree', sans-serif         → all UI text
```

### Key CSS Classes

| Class          | Usage                                               |
|----------------|-----------------------------------------------------|
| `.panel`       | Main content card (bg2, border, border-radius 16px) |
| `.ph`          | Panel header with title + optional right element    |
| `.mc`          | Metric card (bg2, bottom accent line via --mc-line) |
| `.ptable`      | Properties table                                    |
| `.pname`       | Property name (bold, primary text)                  |
| `.pmeta`       | Property subtext (type, small, muted)               |
| `.pcur`        | Current price (mono, text2)                         |
| `.pmkt`        | Market price (mono, text3)                          |
| `.psug`        | Suggested price (mono, bold, primary text)          |
| `.chup`        | Positive price change (green, mono)                 |
| `.chdn`        | Negative price change (red, mono)                   |
| `.sbadge`      | Status badge — `.st-p` pending, `.st-a` applied, `.st-s` skip |
| `.btn`         | Base button — extend with `.b-apply`, `.b-skip`, etc. |
| `.ins-item`    | Insight row with colored dot                        |
| `.itag`        | Insight type tag — `.it-high`, `.it-med`, `.it-info`, `.it-ok` |
| `.season`      | Season badge — `.s-alta`, `.s-media`, `.s-bassa`   |

---

## Filters & Pagination Logic

Properties page filtering happens in `renderProps()`:

```
filtered = PROPS
  .filter(city match if fCity !== 'all')
  .filter(platform match if fPlatform !== 'all')
  .filter(name/city/region includes searchQ)
  .filter(status match for curTab)

pages = ceil(filtered.length / PG)
slice = filtered[(propPage-1)*PG : propPage*PG]
```

Bulk action counts are always computed from the full `PROPS` array (not filtered).

---

## Italian Localization

The entire UI is in Italian. Key terms for consistency:

| English            | Italian used in app               |
|--------------------|-----------------------------------|
| Property           | Proprietà                         |
| Current price      | Prezzo attuale                    |
| Market average     | Media mercato                     |
| AI suggested price | Prezzo suggerito AI / Suggerito   |
| Pending            | In attesa                         |
| Applied            | Applicato                         |
| Skipped            | Saltato                           |
| Apply              | Applica                           |
| Skip               | Salta                             |
| Scan               | Analizza / Scansione              |
| Demand score       | Punteggio domanda / Domanda       |
| High season        | Alta stagione                     |
| Overview           | Panoramica                        |
| History / Log      | Storico                           |
| Settings           | Impostazioni                      |
| Seasonality        | Stagionalità                      |
| Both platforms     | Entrambe                          |
| Urgent             | URGENTE                           |
| Event              | EVENTO                            |

---

## Italian Market Context

When adding properties, insights, or market data, use accurate Italian geography:

### Supported Cities & Regions

| City        | Region       | Season profile         | Price range (EUR/night) |
|-------------|--------------|------------------------|-------------------------|
| Roma        | Lazio        | Media — year-round     | 90 – 360                |
| Firenze     | Toscana      | Alta — spring/summer   | 160 – 540               |
| Venezia     | Veneto       | Alta — Biennale peaks  | 190 – 600               |
| Milano      | Lombardia    | Media — Fashion Week   | 120 – 400               |
| Napoli      | Campania     | Media — year-round     | 80 – 250                |
| Amalfi      | Campania     | Alta — Jun–Sep coastal | 220 – 900               |
| Sicilia     | Sicilia      | Alta — Jul–Aug         | 180 – 550               |
| Sardegna    | Sardegna     | Alta — Jul–Aug         | 140 – 1000              |
| Toscana     | Toscana      | Media — rural/agri     | 210 – 600               |
| Como        | Lombardia    | Alta — spring/summer   | 260 – 750               |

### Seasonal Multipliers

```
Alta stagione  (Lug–Ago, coastal/islands): 2.0× base price
Primavera      (Apr–Giu, cities/lakes):    1.5× base price
Autunno        (Set–Ott, cities + events): 1.3× base price
Bassa stagione (Nov–Mar, most areas):      0.8× base price
```

### Key Italian Events That Affect Pricing

- **Biennale di Venezia** — April to November (odd years): +25–40% for Venice
- **Fashion Week Milano** — September 18–24: +30–40% for Milan
- **Ferragosto** (Aug 15 peak): +50% across all coastal/island areas
- **Easter week**: +20–30% for cities (Roma, Firenze, Napoli)
- **Christmas/New Year**: +30% for ski-adjacent areas (Toscana hills, Como)

---

## How to Extend the App

### Add a new property

Add an object to the `PROPS` array following the data model above. `id` must be unique. `status` should be `"pending"` for new properties.

### Add a new city

1. Add entries to `PROPS` with the new city name.
2. Add a `CITY_MARKETS` entry with `avgPrice`, `occ`, `trend`, `season`.
3. Add the city as an `<option>` in the `#cityFil` select in the topbar HTML.
4. Add the city to the `renderSeasons()` grid if relevant.

### Add a new page

1. Write a `renderXxx()` function that returns an HTML string.
2. Add the page name to the `titles` and `renders` objects in `gotoPage()`.
3. Add a `.nav-item` in the sidebar HTML with `onclick="gotoPage('xxx')"`.
4. If the page has charts, add `buildXxxChart()` calls inside the `setTimeout` in `gotoPage()`.

### Add a real backend / scraper

The `runScan()` function currently only animates UI. To wire it to a real Python scraper:

```js
async function runScan() {
  // ... show loading state ...
  const response = await fetch('/api/scan', { method: 'POST' });
  const data = await response.json();
  // data.properties → update PROPS
  // data.market     → update MARKET_COMPS, CITY_MARKETS
  // re-render current page
}
```

Expected API response shape:
```json
{
  "scanned_at": "2025-03-20T10:22:00Z",
  "listings_count": 3840,
  "properties": [ /* array of PROPS objects with updated mkt + sug */ ],
  "market":     [ /* array of MARKET_COMPS */ ],
  "city_markets": [ /* array of CITY_MARKETS */ ]
}
```

### Change the pricing algorithm

The suggestion formula lives in the scraper/backend (not yet built). In the frontend, `sug` values are hardcoded in `PROPS`. When a real backend exists, the suggested price should arrive pre-calculated. The Settings sliders (floor, ceiling, undercut %, weekend premium) should be sent as query params to `/api/scan`.

---

## Important Constraints

- **Single HTML file** — do not split into separate CSS/JS files unless explicitly asked.
- **No framework** — vanilla JS only. No React, Vue, or bundler.
- **No external requests** — all data is local. The scan button is UI-only for now.
- **Chart.js only** — loaded from `cdnjs.cloudflare.com`. Do not add other charting libs.
- **Google Fonts** — Cormorant Garamond + DM Mono + Figtree. Do not change fonts.
- **Euro pricing** — all prices are in EUR (€), not USD. Never use `$`.
- **Italian UI** — all labels, buttons, tooltips, and notifications must stay in Italian.
- **Dark theme only** — the app has no light mode. Do not add a toggle.
- **Prices are integers** — no decimals on EUR prices. Use `Math.round()` when computing.

---

## Common Tasks

**"Add a property in [city]"**
→ Append to `PROPS` array. Follow the data model exactly. City must exist in `CITY_MARKETS`.

**"Change the color scheme"**
→ Edit the CSS variables in `:root`. Primary accent is `--gold` (#c9973a).

**"Add a new chart"**
→ Create canvas in the relevant `renderXxx()` function, write `buildXxxChart()`, register in `gotoPage()` setTimeout block, add to `charts` object so it can be destroyed on re-render.

**"Make the scan button call a real API"**
→ Replace the `setTimeout` block in `runScan()` with a `fetch('/api/scan')` call. See "Add a real backend" section above.

**"Add a property detail/edit page"**
→ Add a `renderDetail(id)` function, trigger via a row click in `renderProps()`, add `'detail'` to the `gotoPage()` renders map.

**"Export suggestions to CSV"**
→ Add a button that maps `PROPS.filter(p => p.status === 'pending')` to CSV rows and triggers a `data:text/csv` download.

**"Add bulk selection (checkboxes)"**
→ Add a `selectedIds = new Set()` state var, add checkbox column to `ptable`, wire bulk action buttons to operate on `selectedIds` instead of all pending.
