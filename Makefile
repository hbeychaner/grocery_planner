.PHONY: start stop restart test health open-browser help

PYTHON := ./.venv/bin/python3
UVICORN := ./.venv/bin/uvicorn
PYTEST := ./.venv/bin/pytest
APP_URL := http://localhost:8000
DOCS_URL := http://localhost:8000/docs
OLLAMA_URL := http://localhost:11434

# Read LANGFUSE_HOST from .env if present, fallback to Langfuse Cloud
LANGFUSE_URL := $(shell grep -E '^LANGFUSE_HOST=' .env 2>/dev/null | cut -d '=' -f2- | tr -d '"' | tr -d "'")
ifeq ($(LANGFUSE_URL),)
	LANGFUSE_URL := https://cloud.langfuse.com
endif

help:
	@echo "Grocery Price Comparator - Stack Commands"
	@echo "  make start         Start Ollama + FastAPI server and open Chrome tabs"
	@echo "  make stop          Stop FastAPI server"
	@echo "  make restart       Restart the stack"
	@echo "  make open-browser  Open Frontend, API Docs, and Langfuse in Google Chrome"
	@echo "  make health        Check /health endpoint and Ollama status"
	@echo "  make test          Run offline pytest suite"

start:
	@echo "1. Checking Ollama..."
	@if ! curl -sf $(OLLAMA_URL)/api/tags >/dev/null 2>&1; then \
		echo "   Starting Ollama daemon..."; \
		nohup ollama serve >/tmp/ollama.log 2>&1 & \
		for i in 1 2 3 4 5 6 7 8 9 10; do \
			if curl -sf $(OLLAMA_URL)/api/tags >/dev/null 2>&1; then break; fi; \
			sleep 1; \
		done; \
	else \
		echo "   Ollama already running."; \
	fi
	@echo "2. Starting FastAPI (Uvicorn)..."
	@if lsof -ti :8000 >/dev/null 2>&1; then \
		echo "   Port 8000 already active. Restarting..."; \
		lsof -ti :8000 | xargs kill -9 2>/dev/null || true; \
		sleep 1; \
	fi
	@nohup $(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload >/tmp/grocery_planner.log 2>&1 &
	@echo "3. Waiting for backend health check..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
		if curl -sf $(APP_URL)/health >/dev/null 2>&1; then \
			echo "   Backend is up!"; \
			break; \
		fi; \
		sleep 1; \
	done
	@$(MAKE) open-browser
	@echo "Stack is running. Logs: /tmp/grocery_planner.log"

open-browser:
	@echo "4. Opening Google Chrome tabs..."
	@open -a "Google Chrome" "$(APP_URL)" "$(DOCS_URL)" "$(LANGFUSE_URL)"

stop:
	@echo "Stopping FastAPI server on port 8000..."
	@if lsof -ti :8000 >/dev/null 2>&1; then \
		lsof -ti :8000 | xargs kill 2>/dev/null || true; \
		echo "Stopped."; \
	else \
		echo "Not running."; \
	fi

restart: stop start

health:
	@curl -s $(APP_URL)/health | $(PYTHON) -m json.tool
	@ollama ps

test:
	HF_HUB_OFFLINE=1 $(PYTEST) -v
