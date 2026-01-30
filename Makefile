.PHONY: install lint test

install:
	pip install -e .

lint:
	ruff check .
	ruff format --check .

test:
	pytest -q
