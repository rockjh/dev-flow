"""Canonical generated-project paths for the API test domain."""

from pathlib import Path


BRUNO = Path("bruno")
FIXTURES = Path("fixtures")
CONTRACTS = Path("contracts")
CONSTRAINTS = Path("constraints")
EXECUTION = Path("execution")
DESIGN = Path("design")
REPORTS = Path("reports")
LATEST_REPORT = REPORTS / "latest.md"

# API domain assets are rooted at qa/ in generated projects.
