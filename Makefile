.PHONY: install api web test test-api test-web build openapi seed clean

install:
	cd api && python -m pip install -r requirements-dev.txt && ([ -f .env ] || cp .env.example .env)
	cd web && npm install && ([ -f .env ] || cp .env.example .env)

api:
	cd api && uvicorn app.main:app --reload --port 8000

web:
	cd web && npm run dev

test: test-api test-web

test-api:
	cd api && python -m pytest -q

test-web:
	cd web && npm test && npm run build

build:
	cd web && npm run build

openapi:
	cd api && python scripts/export_openapi.py
	cd web && npm run gen:types

clean:
	rm -rf api/voicecircle.db api/storage api/.pytest_cache web/dist
