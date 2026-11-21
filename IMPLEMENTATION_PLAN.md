# Implementation Plan & Developer Handoff Guide

## Grocery Price Comparator: Rohlík.cz vs. Košík.cz (with Google Home / IFTTT)

**Author:** Antigravity Team  
**Last Updated:** November 2026  
**Status:** MVP Implemented, Tested, and Functional (Phase 1 & Phase 2 Complete)  
**Target Location:** Prague, Czechia (e.g. Vinohrady, Italská 13)

---

## 1. Project Overview & Architecture

This application is a real-time grocery price comparator designed for Prague residents ordering from **Rohlík.cz** and **Košík.cz**. It can be queried through an interactive modern **Web UI** or spoken voice commands through **Google Home** (via an **IFTTT** webhook).

### Key Architectural Principles
- **100% Pydantic v2**: All domain models, API requests/responses, and configuration settings are strictly validated Pydantic models.
- **Strict OOP / Extensible Design**: Supermarket clients inherit from an abstract `BaseStoreClient`. Adding a third store (e.g., Tesco, Billa) requires only implementing this interface without altering core comparator logic.
- **Bilingual Intelligence**: The user speaks or enters queries in **English** (e.g., *"butter"*, *"whole milk"*, *"eggs"*), while the backend translates queries to **Czech** terms (e.g., *"máslo"*, *"plnotučné mléko"*, *"vejce"*) for store searches and returns conversational **English** voice summaries.
- **Normalized Unit Price Ranking**: Supermarkets frequently package products in different pack sizes (e.g. 200g vs 250g butter, 10-pack vs 6-pack eggs). Candidates are ranked and compared by **price per kilogram / liter (`CZK/kg`, `CZK/l`)** rather than raw package price.
- **No Scraping Hacks / CAPTCHA Bypasses**: Uses stable, lightweight JSON endpoints discovered from both web platforms.

---

## 2. Directory Structure

```
grocery_planner/
├── .env                          # Local secrets (ignored by git)
├── .env.example                  # Template for environment configuration
├── .gitignore                    # Strict exclusions (.env, .venv, bytecode)
├── CHANGELOG.md                  # Semantic versioning release log
├── Dockerfile                    # Multi-stage production container build
├── docker-compose.yml            # Docker orchestration configuration
├── IMPLEMENTATION_PLAN.md        # Current state and developer handoff (this file)
├── pyproject.toml                # Project metadata, pytest, and pythonpath config
├── README.md                     # User & developer setup guide
├── requirements.txt              # Pinned Python package dependencies
├── config/
│   └── staples.yaml              # Pre-mapped staple products (butter, milk, eggs, etc.)
├── static/
│   ├── index.html                # Responsive web app UI
│   ├── app.js                    # Web UI controller, ranked list renderer, Web Speech API
│   └── style.css                 # Modern CSS styles with responsive flexbox/grid
├── app/
│   ├── __init__.py
│   ├── main.py                   # FastAPI app factory, lifespan, static file mounting
│   ├── core/
│   │   ├── config.py             # Pydantic BaseSettings loading from .env
│   │   └── exceptions.py         # Custom domain exceptions
│   ├── models/
│   │   ├── enums.py              # StoreType, UnitType, PriceAdvantage
│   │   ├── product.py            # StoreProduct domain model
│   │   ├── comparison.py         # MatchedProductPair, ComparisonResponse, Basket models
│   │   ├── staples.py            # StapleDefinition, StaplesCatalog
│   │   └── voice.py              # IFTTTWebhookRequest, GoogleHomeVoiceResponse
│   ├── clients/
│   │   ├── base.py               # Abstract BaseStoreClient(ABC)
│   │   ├── rohlik.py             # RohlikStoreClient (search-metadata endpoint)
│   │   └── kosik.py              # KosikStoreClient (Constructor.io + detail endpoint)
│   ├── services/
│   │   ├── bilingual.py          # BilingualQueryService (EN <-> CS mapping & synonyms)
│   │   ├── matcher.py            # ProductMatchingService (unit price ranking & matching)
│   │   ├── comparator.py         # PriceComparisonService (parallel query orchestration)
│   │   └── voice_formatter.py    # VoiceResponseFormatter (English conversational speech)
│   └── api/
│       ├── deps.py               # FastAPI client & service dependency injection
│       └── v1/
│           ├── router.py         # Aggregated v1 API router
│           ├── compare.py        # GET /api/v1/compare, POST /api/v1/compare/basket
│           ├── voice.py          # POST /api/v1/voice/ifttt, GET /api/v1/voice/query
│           └── staples.py        # GET /api/v1/staples
└── tests/
    ├── conftest.py               # Fixtures, sample products, MockStoreClient
    ├── test_bilingual.py         # Translation & synonym tests
    ├── test_comparator.py        # Single item & basket comparison tests
    ├── test_matcher.py           # Unit price similarity & matching tests
    ├── test_rohlik_client.py     # Parser & mock API tests
    ├── test_kosik_client.py      # Parser & mock API tests
    └── test_voice_api.py         # IFTTT & voice GET endpoint tests
```

---

## 3. Current Implementation State

### 3.1 Store Clients (`app/clients/`)

#### 1. Rohlík.cz Client (`app/clients/rohlik.py`)
- **API Endpoint**: `GET https://www.rohlik.cz/services/frontend-service/search-metadata?search={query}&offset=0&limit={limit}&companyId=1`
- **Output Parsing**:
  - `data.productList[]`: Extracts `productId`, `productName`, `brand`, `price.full`, `pricePerUnit.full`, `unit`, `imgPath`, `link`, `inStock`.
  - Image URL construction: `https://cdn.rohlik.cz{imgPath}`
  - Web URL construction: `https://www.rohlik.cz{link}`
- **Resilience**: Configured with automatic session reuse, 10s timeouts, and custom User-Agent headers.

#### 2. Košík.cz Client (`app/clients/kosik.py`)
- **API Endpoints**:
  1. **Search**: `GET https://ac.cnstrc.com/search/{encoded_query}?key=key_KaoSi20AnZwxsIZ5&num_results_per_page={limit}`
  2. **Product Detail**: `GET https://www.kosik.cz/api/front/product/{id}`
- **Constructor.io API Key**: `key_KaoSi20AnZwxsIZ5` (extracted from the public Košík frontend bundle).
- **Output Parsing**:
  - `product`: Extracts `id`, `name`, `brand.name`, `price`, `pricePerUnit.price`, `pricePerUnit.unit`, `unit`, `image`.
  - Image placeholder replacement: Replaces `"WIDTHxHEIGHT"` in image template string with `"200x200"`.
  - Rounded unit price decimal conversion to prevent floating-point representation artifacts.

---

### 3.2 Product Matching & Ranking (`app/services/matcher.py`)

- **Rank by Unit Price**: `rank_by_unit_price(products)` sorts products ascending by `unit_price` (price per kg or liter), falling back to pack price if unit price is missing.
- **Irrelevant Item Filtering**: Uses `EXCLUSIONS` dictionary to filter peripheral items from staple queries (e.g., excludes croissants, pastries, or spreads when querying for "máslo").
- **Brand vs. Generic Matching**:
  - For brand searches (e.g., *"Pilsner Urquell"* or *"Madeta"*), pairs matching brand items with token similarity scoring.
  - For generic staple searches (e.g., *"butter"* or *"milk"*), identifies the lowest unit-price offer on each store to determine best overall value.
- **Confidence Scoring**: Combines Jaccard token overlap (60%) and character sequence ratio (40%).

---

### 3.3 Domain Services

- **`PriceComparisonService` (`app/services/comparator.py`)**:
  - Fetches top 10 candidates concurrently from both stores using `asyncio.gather`.
  - Populates both `rohlik_ranked` and `kosik_ranked` lists in `ComparisonResponse`.
  - Computes unit-price difference and percentage savings.
- **`VoiceResponseFormatter` (`app/services/voice_formatter.py`)**:
  - Generates spoken summaries optimized for Google Home:
    > *"Rohlik offers the best value for butter with Miil Máslo 82% at 36.90 CZK, which is 147.60 CZK per kg, compared to 174.50 per kg on Kosik."*
- **`BilingualQueryService` (`app/services/bilingual.py`)**:
  - Translates English grocery staples to Czech queries with synonym generation (e.g. `butter` $\rightarrow$ `máslo`, `bananas` $\rightarrow$ `banány`, `milk` $\rightarrow$ `mléko`).

---

### 3.4 Web User Interface (`static/`)

- Served directly from `/` by FastAPI `StaticFiles`.
- **Ranked Candidate Lists**: Displays top candidates per store with `#1`, `#2`, `#3` rank badges.
- **Best Value Highlight**: Automatically highlights the `#1` unit-price winner with a "🏅 Best Value/kg" badge.
- **Voice Readout**: Includes "🔊 Listen (Google Home Preview)" using browser Web Speech API.
- **One-Click Staples**: Chips for instant queries (`Butter`, `Milk`, `Eggs`, `Bananas`, `Pilsner Beer`).
- **IFTTT Setup Modal**: Built-in instructions and code snippets for setting up Google Home.

---

### 3.5 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Web UI Dashboard |
| `GET` | `/health` | Application and store health check |
| `GET` | `/api/v1/compare?q={item}&lang={en\|cs}` | Full comparison with ranked lists |
| `POST` | `/api/v1/compare/basket` | Multi-item shopping basket comparison |
| `POST` | `/api/v1/voice/ifttt` | Webhook for IFTTT Google Assistant routine |
| `GET` | `/api/v1/voice/query?q={item}&lang={en\|cs}` | Direct voice query endpoint |
| `GET` | `/api/v1/staples` | Pre-configured staples catalog |

---

### 3.6 Automated Testing

Run tests with:
```bash
./.venv/bin/pytest
```
- **11 passing unit tests**:
  - `tests/test_bilingual.py`: English $\rightarrow$ Czech translation & brand retention.
  - `tests/test_matcher.py`: Token similarity, tie detection, unit-price difference calculation.
  - `tests/test_comparator.py`: Single item comparison, multi-item basket calculations.
  - `tests/test_rohlik_client.py`: Rohlik JSON parser and mock client.
  - `tests/test_kosik_client.py`: Kosik Constructor.io parser and mock client.
  - `tests/test_voice_api.py`: IFTTT POST webhook and GET voice endpoint responses.

---

## 4. What's Left to Do (Developer Handoff Guide)

The following tasks represent the natural next steps for a developer taking over the codebase:

### Priority 1: GitHub Remote Setup & First Push
The local git repository is initialized with 3 clean commits on `main`. To connect to GitHub:
```bash
git remote add origin https://github.com/<your-username>/grocery_planner.git
git branch -M main
git push -u origin main
```
*Note: Ensure `.env` is never committed. `.gitignore` already excludes it, and this has been verified with `git check-ignore`.*

---

### Priority 2: Public HTTPS Tunnel for IFTTT & Google Home
Google Home / IFTTT requires a publicly accessible HTTPS endpoint. In development, use either:
1. **Cloudflare Tunnel (Recommended, permanent, free)**:
   ```bash
   brew install cloudflared
   cloudflared tunnel --url http://localhost:8000
   ```
2. **ngrok**:
   ```bash
   ngrok http 8000
   ```
Configure the public URL in your IFTTT Applet:
- **Trigger**: Google Assistant $\rightarrow$ "Say a phrase with a text ingredient" (e.g. `check price of $`)
- **Action**: Webhooks $\rightarrow$ Make a web request:
  - **URL**: `https://<tunnel-domain>/api/v1/voice/ifttt`
  - **Method**: `POST`
  - **Content-Type**: `application/json`
  - **Body**: `{"ingredient": "{{TextField}}", "device_id": "google_home"}`

---

### Priority 3: Add Additional Retailers (Tesco, Billa, Kaufland)
The system is built to support additional Prague supermarkets. To add a new store:
1. **Create Client**: Create `app/clients/tesco.py` inheriting from `BaseStoreClient`.
   - Implement `search(query, limit)`, `get_by_id(id)`, `health_check()`, and `close()`.
   - Normalize output into `StoreProduct` models.
2. **Update Enum**: Add `TESCO = "tesco"` to `StoreType` in `app/models/enums.py`.
3. **Inject Dependency**: Update `app/api/deps.py` and `PriceComparisonService` to accept the new store client.
4. **Update Frontend**: Add a third column card in `static/index.html` and `static/app.js`.

---

### Priority 4: Production Caching (Redis or TTLCache)
Because supermarket prices do not change by the minute, query responses (especially for pre-configured staples) should be cached for 15–30 minutes:
- Add `cachetools` or Redis client.
- Cache at the client level (`rohlik.search` / `kosik.search`) or service level (`compare_single_item`).

---

### Priority 5: Add Open-Source License File
The `README.md` and `CHANGELOG.md` mention an open-source license. Create a `LICENSE` file (such as MIT) at the root of the repository.

---

### Priority 6: CI/CD Pipeline
Add a GitHub Actions workflow (`.github/workflows/ci.yml`) to automatically run:
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pytest
```

---

## 5. Local Development Quickstart

### 1. Setup Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env as needed
```

### 3. Run the Development Server
```bash
./.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Open [http://localhost:8000](http://localhost:8000) in your browser.

### 4. Run Automated Tests
```bash
./.venv/bin/pytest -v
```

### 5. Run Live Integration Test
```bash
./.venv/bin/python -c "
import asyncio
from app.clients.rohlik import RohlikStoreClient
from app.clients.kosik import KosikStoreClient
from app.services.comparator import PriceComparisonService

async def test():
    r, k = RohlikStoreClient(), KosikStoreClient()
    svc = PriceComparisonService(rohlik_client=r, kosik_client=k)
    res = await svc.compare_single_item('butter')
    print('Winner:', res.advantage)
    print('Voice:', res.voice_summary_en)
    await r.close()
    await k.close()

asyncio.run(test())
"
```
