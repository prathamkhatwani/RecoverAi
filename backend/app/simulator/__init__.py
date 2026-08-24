"""Head-to-head simulation: same stream, two arms, one scoreboard."""

from .comparison import (
    ArmMetrics,
    CauseComparison,
    SimulationResult,
    run_simulation,
    run_simulation_sync,
)

__all__ = [
    "ArmMetrics",
    "CauseComparison",
    "SimulationResult",
    "run_simulation",
    "run_simulation_sync",
]
