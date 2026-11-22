# Ensures the repo root is on sys.path so `src.contracts` and the
# path-loaded modules resolve identically under pytest and direct runs.
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
