# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-11-21

### Fixed
- **Brand Match Confidence Clamping**: Clamped `match_confidence` in `ProductMatchingService` to `[0.0, 1.0]`, fixing HTTP 500 Pydantic validation errors on brand queries like Pilsner Urquell.
- **Unit Normalization Precedence**: Fixed `_normalize_unit` in both store clients so `"ml"` is evaluated before `"l"` substring checks.
- **Query Relevance Stemming & Out-of-Stock Handling**: Added stem-based relevance checks and category exclusions to prevent out-of-stock items on one supermarket from being falsely paired with unrelated search fallbacks (e.g. kiwi matched to bananas).
- **Voice Response Enum Formatting**: Formatted unit types in voice responses to use their value strings (`kg`, `l`, `pcs`) instead of `UnitType.<NAME>`.
- **Czech Voice Single-Store Handling**: Added single-store availability responses in Czech.

### Added
- **Store Client Test Suites**: Implemented `tests/test_rohlik_client.py` and `tests/test_kosik_client.py`, bringing test coverage to 20 passing unit tests.

## [0.2.0] - 2026-11-21

### Added
- **Normalized Unit Price Ranking**: Dynamic ranking of candidates by price per base unit (`CZK/kg`, `CZK/l`) rather than pure pack price.
- **Top Candidates Display in Web UI**: Side-by-side supermarket cards now render top-ranked products with `#1`, `#2`, `#3` badges and a highlighted "🏅 Best Value/kg" badge.
- **Voice Response Unit Price Details**: Google Home spoken responses now report both the pack price and normalized unit price (`"Rohlik offers the best value for butter with Miil Máslo 82% at 36.90 CZK, which is 147.60 CZK per kg, compared to 174.50 per kg on Kosik"`).
- **Ranked Product Lists in Schema**: Added `rohlik_ranked` and `kosik_ranked` to `ComparisonResponse`.
- **Constructor.io Live Search & Parser for Košík**: Integration with Constructor.io search endpoint and `/api/front/product/{id}` detail endpoint.
- **Frontend Service Metadata Search for Rohlík**: Direct live integration with `/services/frontend-service/search-metadata?companyId=1`.

## [0.1.0] - 2026-11-19

### Added
- Real-time grocery price comparator between Rohlík.cz and Košík.cz.
- Abstract `BaseStoreClient` pattern with concrete `RohlikStoreClient` (wrapping `rohlik-api`) and `KosikStoreClient` (using async HTTP catalog parser).
- 100% Pydantic v2 data models for products, comparison results, and voice payloads.
- `BilingualQueryService` supporting English speech queries, translating to Czech grocery terms with synonym expansion, and responding in conversational English.
- Pre-configured staples catalog (`config/staples.yaml`) for deterministic "apples-to-apples" staple comparisons (milk, butter, eggs, beer, bananas).
- IFTTT Google Assistant webhook integration (`POST /api/v1/voice/ifttt` and `GET /api/v1/voice/query`).
- Interactive lightweight modern Web UI (`/`) with side-by-side product cards, savings badge, unit prices, and speech preview.
- Multi-stage `Dockerfile` and `docker-compose.yml`.
- Comprehensive test suite for comparator, matching, bilingual translation, and API routes.
