"""Lets users invoke as `python -m comparison ...` instead of `comparison.cli`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
