.PHONY: venv
venv:
	uv sync

.PHONY: fmt
fmt:
	uvx isort --profile black --skip .venv --skip examples --skip tests/filecheck .
	uvx autoflake --remove-all-unused-imports --recursive --in-place --exclude .venv,examples,tests/filecheck .
	uvx black --line-length 5000 --exclude '\.venv|examples|tests/filecheck' .
	uvx ruff check --fix --exclude .venv,examples,tests/filecheck .

.PHONY: test
test: fmt
	uv run pytest tests/
	uv run lit tests/filecheck/
