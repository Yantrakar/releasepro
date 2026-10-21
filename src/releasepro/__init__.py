"""releasepro: one gated release run for any repo. Spec: docs/spec/00-product.md."""
from pathlib import Path

__version__ = (Path(__file__).with_name("VERSION").read_text(encoding="utf-8").split() or ["0.0.0"])[0]
