.PHONY: setup_jobsparser_env

setup_jobsparser_env:
	@echo "Navigating to jobsparser and setting up environment..."
	cd jobsparser && \
	echo "Creating virtual environment with uv..." && \
	uv venv && \
	echo "Installing dependencies..." && \
	uv pip install --python .venv/bin/python . && \
	echo "Setup complete. Virtual environment created and dependencies installed in jobsparser/.venv" 

.PHONY: clean-jobsparser build-jobsparser publish-jobsparser test-install-jobsparser

clean-jobsparser:
	@echo "Cleaning up build artifacts for jobsparser..."
	rm -rf jobsparser/dist

build-jobsparser:
	@echo "Building the jobsparser package with uv..."
	cd jobsparser && uv build

publish-jobsparser:
	make clean-jobsparser
	make build-jobsparser
	@echo "Publishing the jobsparser package with uv..."
	if [ -f .env ]; then \
		echo "Loading environment variables from .env..."; \
		set -a; \
		. ./.env; \
		set +a; \
	else \
		echo "No .env file found in jobsparser directory, proceeding without loading environment variables."; \
	fi && \
	uv publish --directory jobsparser

test-install-jobsparser: build-jobsparser
	@echo "Testing jobsparser package installation with uv..."
	cd jobsparser && uv run --with jobsparser --no-project --python .venv/bin/python -c "import jobsparser" 

.PHONY: setup_jobspy2_env

setup_jobspy2_env:
	@echo "Navigating to jobspy2 and setting up environment..."
	cd jobspy2 && \
	echo "Creating virtual environment with uv..." && \
	uv venv && \
	echo "Installing dependencies..." && \
	uv pip install --python .venv/bin/python . && \
	echo "Setup complete. Virtual environment created and dependencies installed in jobspy2/.venv"

.PHONY: clean-jobspy2 build-jobspy2 publish-jobspy2 test-install-jobspy2

clean-jobspy2:
	@echo "Cleaning up build artifacts for jobspy2..."
	rm -rf jobspy2/dist

build-jobspy2:
	@echo "Building the jobspy2 package with uv..."
	cd jobspy2 && uv build

publish-jobspy2:
	make clean-jobspy2
	make build-jobspy2
	@echo "Publishing the jobspy2 package with uv..."
	if [ -f .env ]; then \
		echo "Loading environment variables from .env..."; \
		set -a; \
		. ./.env; \
		set +a; \
	else \
		echo "No .env file found in jobspy2 directory, proceeding without loading environment variables."; \
	fi && \
	uv publish --directory jobspy2

test-install-jobspy2: build-jobspy2
	@echo "Testing jobspy2 package installation with uv..."
	cd jobspy2 && uv run --with jobspy2 --no-project --python .venv/bin/python -c "import jobspy2" 
