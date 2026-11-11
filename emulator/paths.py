"""Locations inside the repository."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_DIR = ROOT / "target"
EVALUATION_DIR = ROOT / "evaluation"
RESULTS_DIR = EVALUATION_DIR / "results"
VERIFICATION_DIR = EVALUATION_DIR / "verification"
BUILD_DIR = ROOT / "build"          # generated artifacts; not version controlled
