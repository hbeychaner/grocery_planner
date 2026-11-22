.PHONY: start stop stop-all restart test health open-browser langfuse-up langfuse-down track-prices caddy-start caddy-stop tunnel-start tunnel-stop help

PYTHON := ./.venv/bin/python3
UVICORN := ./.venv/bin/uvicorn
PYTEST := ./.venv/bin/pytest
SSL_CERT ?= 192.168.2.47+2.pem
SSL_KEY ?= 192.168.2.47+2-key.pem
ifneq ($(wildcard $(SSL_CERT)),)
ifneq ($(wildcard $(SSL_KEY)),)
	APP_URL := https://localhost:8000
	DOCS_URL := https://localhost:8000/docs
	UVICORN_SSL_FLAGS := --ssl-keyfile $(SSL_KEY) --ssl-certfile $(SSL_CERT)
else
	APP_URL := http://localhost:8000
	DOCS_URL := http://localhost:8000/docs
	UVICORN_SSL_FLAGS :=
endif
else
	APP_URL := http://localhost:8000
	DOCS_URL := http://localhost:8000/docs
	UVICORN_SSL_FLAGS :=
endif
OLLAMA_URL := http://localhost:11434
LANGFUSE_COMPOSE := docker-compose.langfuse.yml

# Read LANGFUSE_HOST from .env if present, fallback to local self-hosted Langfuse
LANGFUSE_URL := $(shell grep -E '^LANGFUSE_HOST=' .env 2>/dev/null | cut -d '=' -f2- | tr -d '"' | tr -d "'")
ifeq ($(LANGFUSE_URL),)
	LANGFUSE_URL := http://localhost:3000
endif

help:
	@echo "Grocery Price Comparator - Stack Commands"
	@echo "  make start         Start Ollama, self-hosted Langfuse (Docker), FastAPI, and open Chrome"
	@echo "  make stop          Stop FastAPI server"
	@echo "  make stop-all      Stop FastAPI server AND Langfuse Docker containers"
	@echo "  make restart       Restart FastAPI and services"
	@echo "  make langfuse-up   Start self-hosted Langfuse stack via Docker Compose"
	@echo "  make langfuse-down Stop self-hosted Langfuse Docker containers"
	@echo "  make open-browser  Open Frontend, API Docs, and Langfuse in Google Chrome"
	@echo "  make health        Check /health endpoint, Langfuse, and Ollama status"
	@echo "  make test          Run offline pytest suite"
	@echo "  make track-prices  Run weekly grocery price tracking sweep (all items)"
	@echo "  make caddy-start   Start Caddy HTTPS reverse proxy (requires PUBLIC_DOMAIN in .env)"
	@echo "  make caddy-stop    Stop Caddy reverse proxy"
	@echo "  make tunnel-start  Start open-source cloudflared public HTTPS tunnel (no port forwarding)"
	@echo "  make tunnel-stop   Stop cloudflared public HTTPS tunnel"

langfuse-up:
	@echo "Starting self-hosted Langfuse (Docker Compose)..."
	@if ! docker info >/dev/null 2>&1; then \
		echo "   Docker daemon is not running. Launching Docker Desktop..."; \
		open -a Docker; \
		for i in $$(seq 1 30); do \
			if docker info >/dev/null 2>&1; then break; fi; \
			sleep 2; \
		done; \
	fi
	@if ! docker info >/dev/null 2>&1; then \
		echo "   ERROR: Docker daemon did not start in time. Start Docker Desktop and re-run."; \
		exit 1; \
	fi
	@docker compose -f $(LANGFUSE_COMPOSE) --env-file .env up -d
	@echo "   Waiting for Langfuse web UI on $(LANGFUSE_URL)..."
	@for i in $$(seq 1 45); do \
		if curl -sf $(LANGFUSE_URL)/api/public/health >/dev/null 2>&1 || curl -sf $(LANGFUSE_URL) >/dev/null 2>&1; then \
			echo "   Langfuse is up!"; \
			break; \
		fi; \
		sleep 2; \
	done

langfuse-down:
	@echo "Stopping self-hosted Langfuse containers..."
	@docker compose -f $(LANGFUSE_COMPOSE) --env-file .env down

start:
	@echo "1. Checking Ollama..."
	@if ! curl -sf $(OLLAMA_URL)/api/tags >/dev/null 2>&1; then \
		echo "   Starting Ollama daemon..."; \
		nohup ollama serve >/tmp/ollama.log 2>&1 & \
		for i in $$(seq 1 10); do \
			if curl -sf $(OLLAMA_URL)/api/tags >/dev/null 2>&1; then break; fi; \
			sleep 1; \
		done; \
	else \
		echo "   Ollama already running."; \
	fi
	@echo "2. Ensuring self-hosted Langfuse is running..."
	@$(MAKE) langfuse-up
	@echo "3. Starting FastAPI (Uvicorn)..."
	@if lsof -ti :8000 >/dev/null 2>&1; then \
		echo "   Port 8000 already active. Restarting..."; \
		lsof -ti :8000 | xargs kill -9 2>/dev/null || true; \
		sleep 1; \
	fi
	@nohup $(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload --proxy-headers --forwarded-allow-ips=127.0.0.1 $(UVICORN_SSL_FLAGS) >/tmp/grocery_planner.log 2>&1 &
	@echo "4. Waiting for backend health check..."
	@for i in $$(seq 1 15); do \
		if curl -sfk $(APP_URL)/health >/dev/null 2>&1; then \
			echo "   Backend is up!"; \
			break; \
		fi; \
		sleep 1; \
	done
	@$(MAKE) open-browser
	@echo "Stack is running. Backend logs: /tmp/grocery_planner.log"

open-browser:
	@echo "5. Opening Google Chrome tabs..."
	@open -a "Google Chrome" "$(APP_URL)/trends" "$(LANGFUSE_URL)" "$(APP_URL)"

track-prices:
	$(PYTHON) -m scripts.run_weekly_check

stop:
	@echo "Stopping FastAPI server on port 8000..."
	@if lsof -ti :8000 >/dev/null 2>&1; then \
		lsof -ti :8000 | xargs kill 2>/dev/null || true; \
		echo "Stopped."; \
	else \
		echo "Not running."; \
	fi

stop-all: stop langfuse-down

restart: stop start

health:
	@curl -sk $(APP_URL)/health | $(PYTHON) -m json.tool
	@echo "Langfuse UI: $$(curl -sf $(LANGFUSE_URL)/api/public/health >/dev/null 2>&1 && echo 'healthy' || echo 'unreachable')"
	@ollama ps

test:
	HF_HUB_OFFLINE=1 $(PYTEST) -v

caddy-start:
	@PUBLIC_DOMAIN=$$(grep -E '^PUBLIC_DOMAIN=' .env 2>/dev/null | cut -d '=' -f2- | tr -d '"' | tr -d "'"); \
	if [ -z "$$PUBLIC_DOMAIN" ]; then \
		echo "ERROR: Set PUBLIC_DOMAIN=yourname.duckdns.org in .env first."; \
		exit 1; \
	fi; \
	PUBLIC_DOMAIN="$$PUBLIC_DOMAIN" nohup caddy run --config Caddyfile >/tmp/caddy_grocery.log 2>&1 & \
	echo "Caddy started for https://$$PUBLIC_DOMAIN (logs: /tmp/caddy_grocery.log)"

caddy-stop:
	@pkill -f "caddy run --config Caddyfile" 2>/dev/null && echo "Caddy stopped." || echo "Caddy not running."

tunnel-start:
	@pkill -f "cloudflared tunnel" 2>/dev/null || true
	@nohup cloudflared tunnel --url https://localhost:8000 --no-tls-verify >/tmp/cloudflared_grocery.log 2>&1 &
	@echo "Waiting for Cloudflare Tunnel URL..."
	@for i in $$(seq 1 15); do \
		URL=$$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cloudflared_grocery.log 2>/dev/null | head -n 1); \
		if [ -n "$$URL" ]; then \
			echo "Public HTTPS URL: $$URL"; \
			break; \
		fi; \
		sleep 1; \
	done

tunnel-stop:
	@pkill -f "cloudflared tunnel" 2>/dev/null && echo "Cloudflare Tunnel stopped." || echo "Cloudflare Tunnel not running."
