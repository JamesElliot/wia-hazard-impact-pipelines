.PHONY: install lint test

install:
	python -m pip install -e '.[dev]' --no-build-isolation

lint:
	ruff check .
	ruff format --check .

test:
	pytest -q
