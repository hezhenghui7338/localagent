"""Scenario eval CLI: python -m benchmarks.eval run --tier smoke|full"""

from benchmarks.eval.runners.run_scenarios import main

if __name__ == "__main__":
    raise SystemExit(main())
