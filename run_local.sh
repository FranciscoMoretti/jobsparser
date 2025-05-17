#!/bin/bash
# Helper script to run the local jobsparser package using uv.
# Assumes this script is run from the repository root.

# All arguments passed to this script will be forwarded to the jobsparser command.
uv run --directory ./jobsparser jobsparser "$@" 