# AGENTS.md

Instructions for AI coding agents working in this repository.

## Project overview

`awspub` is a configuration-driven tool for publishing images (built from
`.vmdk` files) to AWS. Given a YAML configuration file, it:

- Uploads source `.vmdk` files to an S3 bucket
- Creates EC2 snapshots from the uploaded file, copied across configured regions
- Registers/updates EC2 AMIs (images) from those snapshots
- Submits AMIs as new versions to the AWS Marketplace (Marketplace Catalog API)
- Updates SSM parameters (e.g. so consumers can look up the latest AMI ID per region)
- Publishes notifications via SNS

It is installed as the `awspub` CLI (entry point defined in `pyproject.toml`,
implemented in `awspub/cli/`).

## Repository layout

- `awspub/` — main Python package
- `docs/` — Sphinx documentation (config samples, how-to guides, reference docs)
- `snap/` — snapcraft packaging
- `pyproject.toml` / `poetry.lock` — dependencies, managed with Poetry
- `tox.ini` — defines the `test`, `lint`, `type`, and `format` environments

## Setup

Dependencies are managed with [Poetry](https://python-poetry.org/) and tasks
are run through [tox](https://tox.wiki/). Don't install new tooling; use what
tox/poetry already provide.

```bash
poetry install --with test,type,doc
```

## Build, test, and lint

Always prefer running these through `tox` (matches CI):

```bash
tox -e py3       # run unit tests with coverage (pytest + coverage report)
tox -e lint      # flake8, black --check, isort --check
tox -e type      # mypy
tox -e format    # auto-format with black + isort (run before committing)
```

Run a single test file/case directly with poetry if iterating quickly:

```bash
poetry run pytest awspub/tests/test_image.py -k some_test --import-mode importlib
```

- Line length limit is **120** characters (black, flake8).
- Import sorting follows the `black` profile via `isort`.
- Config models use `pydantic` `BaseModel` with `model_config = ConfigDict(extra="forbid")`
  — keep this pattern for any new config sections so unknown YAML keys are rejected.

## Conventions

- Type hints are required throughout; `mypy` runs in strict-ish mode via `tox -e type`.
- New config options belong in `awspub/configmodels.py`, with a `Field(description=...)`
  for documentation (docs use `autodoc_pydantic` to render these automatically).
- Add/adjust unit tests under `awspub/tests/` alongside any behavior change; use
  `awspub/tests/fixtures/` for sample YAML/config data instead of inlining large fixtures.
- Keep AWS API interactions isolated in their respective modules (`s3.py`, `snapshot.py`,
  `image.py`, `image_marketplace.py`, `sns.py`) rather than calling boto3 directly from `api.py`/`cli/`.

## Documentation

Docs live under `docs/` and build with Sphinx (see `.readthedocs.yaml`). Update
relevant `docs/reference` or `docs/how_to` pages when changing config schema or CLI behavior.

## Before committing

1. `tox -e format` (or run `black`/`isort` manually) to auto-fix style.
2. `tox -e lint`, `tox -e type`, and `tox -e py3` (or targeted `pytest`) must pass.
3. Do not commit `.coverage`, `.mypy_cache`, `.pytest_cache`, `.tox`, or `.venv` artifacts.
