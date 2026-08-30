from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Callable, Iterable, Any


@dataclass(frozen=True)
class SensitivityResult:
    parameters: dict[str, Any]
    return_pct: float
    profit_factor: float
    drawdown_pct: float
    win_rate_pct: float


@dataclass(frozen=True)
class SensitivityReport:
    results: tuple[SensitivityResult, ...]

    @property
    def best_result(self) -> SensitivityResult | None:
        if not self.results:
            return None
        return max(
            self.results,
            key=lambda item: (item.profit_factor, item.return_pct),
        )


def generate_parameter_sets(parameter_space: dict[str, Iterable[Any]]) -> list[dict[str, Any]]:
    keys = list(parameter_space.keys())
    values = [list(parameter_space[key]) for key in keys]
    return [dict(zip(keys, combination)) for combination in product(*values)]


def run_sensitivity_analysis(
    parameter_space: dict[str, Iterable[Any]],
    evaluator: Callable[[dict[str, Any]], dict[str, float]],
) -> SensitivityReport:
    results: list[SensitivityResult] = []

    for params in generate_parameter_sets(parameter_space):
        metrics = evaluator(params)
        results.append(
            SensitivityResult(
                parameters=params,
                return_pct=float(metrics.get("return_pct", 0.0)),
                profit_factor=float(metrics.get("profit_factor", 0.0)),
                drawdown_pct=float(metrics.get("drawdown_pct", 0.0)),
                win_rate_pct=float(metrics.get("win_rate_pct", 0.0)),
            )
        )

    return SensitivityReport(tuple(results))
