.PHONY: venv fmt

venv:
	uv sync

fmt:
	uvx isort .
	uvx autoflake --remove-all-unused-imports --recursive --in-place .
	uvx black --line-length 5000 .
	uvx ruff check --fix .
