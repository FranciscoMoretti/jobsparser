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
