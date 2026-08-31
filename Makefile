PYTHON ?= python3

.PHONY: build check check-components demo evidence-integrity install-dev installed-smoke provenance review smoke test verify-dist

install-dev:
	$(PYTHON) -m pip install -e '.[dev]'

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

demo:
	PYTHONPATH=src $(PYTHON) examples/synthetic_demo.py

smoke:
	PYTHONPATH=src $(PYTHON) -c "import codex_collaboration_harness; print(codex_collaboration_harness.__name__)"

installed-smoke:
	$(PYTHON) -I -c "import importlib.metadata as metadata; import codex_collaboration_harness as harness; print(metadata.version('codex-collaboration-harness'), harness.__name__)"

provenance:
	$(PYTHON) scripts/check_provenance.py

evidence-integrity: provenance

review:
	$(PYTHON) scripts/review_readiness.py

check: review provenance test demo smoke

check-components:
	$(PYTHON) scripts/check_components.py

build:
	$(PYTHON) -m build --sdist --wheel

verify-dist:
	$(PYTHON) scripts/verify_dist.py
