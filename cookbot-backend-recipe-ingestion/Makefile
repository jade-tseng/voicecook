URLS ?= seed_urls.example.txt
CONCURRENCY ?= 10
LIMIT ?=

.PHONY: seed test

seed:
	docker compose exec api python -m scripts.seed \
		--urls /app/$(URLS) \
		--concurrency $(CONCURRENCY) \
		$(if $(LIMIT),--limit $(LIMIT),)

test:
	docker compose exec api python -m pytest tests/ -q
