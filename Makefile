# Claim2CAD — top-level Makefile.
#
# Common targets:
#   make install   — provision .venv with runtime + test deps
#   make demo      — regenerate the golden_robot_arm example end-to-end
#   make test      — run pytest
#   make clean     — remove generated CAD artifacts (keeps source files)

PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
EXAMPLE ?= golden_robot_arm

.PHONY: install demo demo-all test clean viewer viewer-install viewer-build viewer-dev help

help:
	@echo "Available targets:"
	@echo "  install        — create .venv and install requirements.txt"
	@echo "  demo           — run the pipeline on examples/$(EXAMPLE)/claim.txt"
	@echo "  demo-all       — run the pipeline on every example/* directory"
	@echo "  test           — pytest with the local venv"
	@echo "  viewer-install — npm install in viewer/"
	@echo "  viewer-build   — vite build of the viewer"
	@echo "  viewer-dev     — stage data into viewer/public/data and run the dev server"
	@echo "  clean          — remove generated CAD artifacts under examples/*/"

install:
	test -d .venv || python3.11 -m venv .venv
	$(PIP) install --upgrade pip --quiet
	$(PIP) install -r requirements.txt

demo:
	$(PY) -m claim2cad.pipeline \
		--claim examples/$(EXAMPLE)/claim.txt \
		--out   examples/$(EXAMPLE) \
		--example-name $(EXAMPLE)

demo-all:
	@for ex in examples/*/; do \
		name=$$(basename $$ex); \
		test -f $$ex/claim.txt || continue; \
		echo "==> $$name"; \
		$(PY) -m claim2cad.pipeline --claim $$ex/claim.txt --out $$ex --example-name $$name; \
	done

test:
	$(PY) -m pytest -q

viewer-install:
	cd viewer && npm install --no-audit --no-fund

viewer-build:
	$(PY) -m claim2cad.manifest
	cd viewer && npm run build

viewer-dev:
	$(PY) -m claim2cad.manifest
	cd viewer && npm run dev

viewer: viewer-build

clean:
	@find examples -maxdepth 2 -type f \( \
		-name "model.step" -o \
		-name "model.glb" -o \
		-name "claim_ir.json" -o \
		-name "claim_map.json" \
	\) -print -delete
	@find examples -maxdepth 2 -name "generator.py" -newer claim2cad/ir_to_cad.py -print -delete || true
