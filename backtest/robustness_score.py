from __future__ import annotations

from dataclasses import dataclass

from backtest.validation_v2 import RobustValidation


@dataclass(frozen=True)
class RobustnessScore:
    score: float
    grade: str
    approved: bool
    reasons: tuple[str, ...]


def calculate_robustness_score(validation: RobustValidation) -> RobustnessScore:
    """Convert validation results into a deterministic robustness score.

    This is not a replacement for validation. It is a reporting layer that
    makes the decision process explicit and prevents approving strategies
    based on a single attractive backtest period.
    """
    score = 0.0
    reasons: list[str] = []

    fold_count = len(validation.folds)
    if fold_count >= 3:
        score += 20
    else:
        reasons.append("less than three validation folds")

    if validation.total_oos_trades >= validation.min_trades_per_fold * max(fold_count, 1):
        score += 20
    else:
        reasons.append("insufficient out-of-sample trades")

    if validation.performance_failures == 0:
        score += 25
    else:
        reasons.append("out-of-sample performance failure detected")

    if validation.median_oos_profit_factor > 1.05:
        score += 20
    else:
        reasons.append("median out-of-sample profit factor is weak")

    if validation.median_pf_retention_pct >= 50:
        score += 15
    else:
        reasons.append("profit factor retention is below threshold")

    approved = score >= 80 and not validation.performance_failures

    if score >= 90:
        grade = "A"
    elif score >= 80:
        grade = "B"
    elif score >= 60:
        grade = "C"
    else:
        grade = "D"

    return RobustnessScore(
        score=score,
        grade=grade,
        approved=approved,
        reasons=tuple(reasons),
    )
