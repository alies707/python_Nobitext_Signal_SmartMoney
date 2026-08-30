from __future__ import annotations

"""Utilities for generating robustness validation reports."""

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from backtest.validation_v2 import RobustValidation


def build_robustness_report(validation: RobustValidation) -> dict[str, Any]:
    """Convert a RobustValidation result into a JSON serializable report."""
    folds = []
    for fold in validation.folds:
        folds.append(
            {
                "fold_id": fold.fold_id,
                "sample_status": fold.sample_status(validation.min_trades_per_fold),
                "performance_status": fold.performance_status(
                    validation.min_trades_per_fold
                ),
                "failure_reasons": list(
                    fold.performance_failure_reasons(validation.min_trades_per_fold)
                ),
                "oos_trades": fold.out_of_sample_performance.total_trades,
                "oos_profit_factor": fold.out_of_sample_performance.profit_factor,
                "oos_return_pct": fold.out_of_sample_performance.total_return_pct,
                "oos_drawdown_pct": fold.out_of_sample_performance.max_drawdown_pct,
                "pf_retention_pct": fold.oos_pf_retention_pct,
            }
        )

    return {
        "fold_count": len(validation.folds),
        "total_oos_trades": validation.total_oos_trades,
        "aggregate_oos_pnl": validation.aggregate_oos_pnl,
        "aggregate_oos_return_pct": validation.aggregate_oos_return_pct,
        "median_oos_profit_factor": validation.median_oos_profit_factor,
        "median_pf_retention_pct": validation.median_pf_retention_pct,
        "worst_oos_profit_factor": validation.worst_oos_profit_factor,
        "passes_preliminary_robustness": validation.passes_preliminary_robustness,
        "folds": folds,
    }


def save_robustness_report(validation: RobustValidation, path: str) -> None:
    """Save robustness validation output as JSON."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(build_robustness_report(validation), indent=2),
        encoding="utf-8",
    )
