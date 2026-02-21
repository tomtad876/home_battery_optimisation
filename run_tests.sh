#!/bin/bash
# Quick test commands

# Run all tests
pytest

# Run tests with coverage
pytest --cov=app --cov-report=html

# Run only optimiser tests
pytest tests/test_optimiser.py -v

# Run only service tests
pytest tests/test_services.py -v

# Run only route tests
pytest tests/test_routes.py -v

# Run a specific test
pytest tests/test_optimiser.py::TestOptimiser::test_optimiser_respects_soc_bounds -v
