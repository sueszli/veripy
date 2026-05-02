.PHONY: venv fmt test

venv:
	uv sync

fmt:
	uvx isort --profile black --skip .venv --skip examples --skip tests/filecheck .
	uvx autoflake --remove-all-unused-imports --recursive --in-place --exclude .venv,examples,tests/filecheck .
	uvx black --line-length 5000 --exclude '\.venv|examples|tests/filecheck' .
	uvx ruff check --fix --exclude .venv,examples,tests/filecheck .

test: fmt
	uv run pytest tests/
	uv run lit tests/filecheck/
