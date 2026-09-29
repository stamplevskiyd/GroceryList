# Тонкая обёртка над scripts/ (ADR-0007): своей логики здесь нет.
.PHONY: fmt lint typecheck test check

fmt lint typecheck check:
	./scripts/$@.sh

test:
	./scripts/test.sh $(ARGS)
