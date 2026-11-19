# Grocery Price Comparator (Košík vs. Rohlík) 🛒🇨🇿

A modern, production-grade Python FastAPI application that compares grocery prices between **Rohlík.cz** and **Košík.cz** in real-time, helping you instantly determine which supermarket offers the best price for your grocery run in Prague.

Reachable both via an interactive **modern Web UI** and as a voice fulfillment API for **Google Home** via **IFTTT**.

---

## ✨ Key Features

- **No Reinventing the Wheel**: Directly integrates with existing public interfaces and open-source packages (`rohlik-api`).
- **Bilingual Intelligence**: You can speak or search in **English** (e.g., *"butter"*, *"whole milk"*, *"pilsner urquell"*); the internal `BilingualQueryService` automatically maps and expands terms into Czech for the store catalogs, and formulates conversational voice responses in English.
- **Fair Unit Price Matching**: Computes accurate price differences and handles unit normalization (e.g. per 100g, 1kg, 1L) so package differences don't distort comparisons.
- **Pre-Configured Staples**: Includes a catalog of canonical staples (`config/staples.yaml`) for 1-click "apples-to-apples" comparison (e.g. butter 250g, eggs 10pcs, milk 1L).
- **Google Home via IFTTT**: Optimized voice webhook endpoint (`POST /api/v1/voice/ifttt`) ready for Google Assistant *"Say a phrase with a text ingredient"* routines.
- **Interactive Web App**: Lightweight, responsive frontend (`/`) with live search, side-by-side product cards, savings badges, and browser speech simulation.
- **Professional Code Quality**:
  - 100% **Pydantic v2** models and `pydantic-settings`.
  - Object-Oriented Architecture (`BaseStoreClient(ABC)`).
  - Strong typing compliant with `mypy --strict`.
  - Docker & Docker Compose ready.

---

## 🏗️ Project Architecture

```
grocery_planner/
├── app/
│   ├── main.py                     # FastAPI application & lifespan
│   ├── core/                       # AppSettings & custom exceptions
│   ├── models/                     # 100% Pydantic models (products, comparison, voice)
│   ├── clients/                    # BaseStoreClient, RohlikStoreClient, KosikStoreClient
│   ├── services/                   # BilingualQueryService, ProductMatchingService,
│   │                               # PriceComparisonService, VoiceResponseFormatter
│   └── api/                        # FastAPI v1 routes (/compare, /voice, /staples)
├── config/
│   └── staples.yaml                # Pre-defined canonical staple products
├── static/                         # Lightweight Web UI (HTML, CSS, JS)
├── tests/                          # Automated Pytest suite
├── Dockerfile                      # Multi-stage secure Docker build
├── docker-compose.yml              # Local container orchestration
├── pyproject.toml                  # Project metadata & mypy configuration
├── .env.example                    # Template for environment variables
└── CHANGELOG.md                    # Release history
```

---

## 🚀 Quick Start (Local Setup)

### 1. Clone & Set Up Environment
```bash
git clone https://github.com/<your-username>/grocery_planner.git
cd grocery_planner

# Copy environment template
cp .env.example .env

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Run Application
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- **Web App**: Open [http://localhost:8000](http://localhost:8000)
- **Interactive Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check**: [http://localhost:8000/health](http://localhost:8000/health)

---

## 🐳 Running with Docker

```bash
# Build and run container
docker compose up -d --build

# View logs
docker compose logs -f

# Stop container
docker compose down
```

---

## 🗣️ Google Home Setup via IFTTT

You can connect your Google Home / Google Assistant to this API in 3 minutes:

### 1. Expose your API securely to the Internet
Google Home needs an HTTPS URL to reach your local server. You can use **Cloudflare Tunnel** (recommended & free) or **ngrok**:
```bash
cloudflared tunnel --url http://localhost:8000
# or
ngrok http 8000
```
Note your public HTTPS domain (e.g., `https://grocery.yourdomain.com`).

### 2. Create the IFTTT Applet
1. Go to [IFTTT Applet Create](https://ifttt.com/create).
2. **If This**:
   - Choose service: **Google Assistant**.
   - Select trigger: **"Say a phrase with a text ingredient"**.
   - What do you want to say?:
     - `Check price of $`
     - `Compare price of $`
     - `Who is cheaper for $`
3. **Then That**:
   - Choose service: **Webhooks**.
   - Select action: **"Make a web request"**.
   - **URL**: `https://grocery.yourdomain.com/api/v1/voice/ifttt`
   - **Method**: `POST`
   - **Content Type**: `application/json`
   - **Body**:
     ```json
     {
       "ingredient": "{{TextField}}"
     }
     ```
4. Click **Finish**.

Now say to your Google Home:
> *"Hey Google, check price of butter"*
> 
> *Google Home will reply:*
> **"Rohlik is cheaper for butter. It costs 52.90 CZK compared to 59.90 CZK on Kosik, saving you 7.00 CZK."**

---

## 🧪 Running Tests & Type Checking

```bash
# Run automated test suite
pytest

# Run strict type checking
mypy app
```

---

## 🔒 Security Policy
- Credentials and sensitive tokens belong exclusively in `.env` (which is excluded in `.gitignore`).
- Never commit credentials to version control.
- In Docker, the container executes under an unprivileged `appuser` (non-root).

---

## 📜 Changelog
See [CHANGELOG.md](CHANGELOG.md) for version release details.
