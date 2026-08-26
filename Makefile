.PHONY: install test up down health pilot

install:
	pip install -e ".[dev]"
	cp -n config/.env.example .env || true

test:
	pytest -v

up:
	sandbox up --profile ollama

down:
	sandbox down --profile ollama

health:
	sandbox health --profile ollama

pilot:
	sandbox pilot --mock
