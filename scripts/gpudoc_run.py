"""Runs gpudoc from a copied folder. Embeddable Python ignores PYTHONPATH and the script's folder."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gpudoc.cli import main  # noqa: E402

sys.exit(main())
