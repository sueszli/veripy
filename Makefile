.PHONY: venv fmt precommit

venv:
	uv sync

fmt:
	uvx isort .
	uvx autoflake --remove-all-unused-imports --recursive --in-place .
	uvx black --line-length 5000 --target-version py312 .
	uvx ruff check --fix .

precommit: fmt
	uv run pytest
