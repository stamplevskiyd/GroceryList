# Тонкая обёртка над scripts/ (ADR-0007): своей логики здесь нет.
.PHONY: fmt lint typecheck test check api

fmt lint typecheck check api:
	./scripts/$@.sh

test:
	./scripts/test.sh $(ARGS)
