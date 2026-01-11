.PHONY: build tag push publish test lint format check fix

TAG ?= latest

build:
	docker build -t clipcast .

tag:
	docker tag clipcast ghcr.io/elgrove/clipcast:$(TAG)

push:
	docker push ghcr.io/elgrove/clipcast:$(TAG)

publish: build tag push

test:
	uv run pytest

format:
	uv run ruff format .

fix:
	-uv run ruff check --fix .
	uv run ruff format .
