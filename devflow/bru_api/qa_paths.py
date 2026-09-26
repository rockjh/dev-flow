"""Canonical generated-project paths for the API test domain."""

from pathlib import Path


BRUNO = Path("bruno")
CONTRACTS = Path("contracts")
CONSTRAINTS = Path("constraints")
EXECUTION = Path("execution")
RESULTS = Path("artifacts")
GLOBAL_RESULTS = RESULTS / "global"
MODULE_RESULTS = RESULTS / "modules"
GLOBAL_EVIDENCE = GLOBAL_RESULTS / "evidence"
MODULE_EVIDENCE = MODULE_RESULTS / "evidence"
LOGS = RESULTS / "logs"

# API domain assets are rooted at test/bru-api in generated projects.
