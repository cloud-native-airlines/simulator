.PHONY: help venv install run docker-run test build-image push-image clean

# --- configuration (override on the command line, e.g. `make push REGISTRY=ghcr.io/cloud-native-airlines`) ---
PYTHON  ?= python3
VENV    := .venv
BIN     := $(VENV)/bin
PORT    ?= 8000

IMAGE     ?= cna-simulator
TAG       ?= latest
REGISTRY  ?=
IMAGE_REF := $(if $(REGISTRY),$(REGISTRY)/,)$(IMAGE):$(TAG)

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

$(VENV)/.installed: pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -e ".[dev]"
	@touch $@

install: $(VENV)/.installed ## Create the venv and install the package (with dev extras)

run: install ## Run the simulator locally with Python (http://localhost:$(PORT))
	SIM_PORT=$(PORT) $(BIN)/python -m simulator

test: install ## Run the test suite
	$(BIN)/python -m pytest

build-image: ## Build the Docker image ($(IMAGE_REF))
	docker build -t $(IMAGE_REF) .

docker-run: build-image ## Build then run the image, publishing the port
	docker run --rm -p $(PORT):8000 $(IMAGE_REF)

push-image: build-image ## Build and push the image to the registry (set REGISTRY)
	@if [ -z "$(REGISTRY)" ]; then \
		echo "REGISTRY is not set. Example: make push REGISTRY=ghcr.io/cloud-native-airlines TAG=v0.1.0"; \
		exit 1; \
	fi
	docker push $(IMAGE_REF)

clean: ## Remove the venv and build/test caches
	rm -rf $(VENV) .pytest_cache src/*.egg-info src/cna_simulator.egg-info build dist

.DEFAULT_GOAL := help
