
"""Token budget calculator — keeps memory injection within limits."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class BudgetAllocation:
    """How much token budget each layer gets for a given query."""
    layer: int
    name: str
    allocated_chars: int
    used_chars: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.allocated_chars - self.used_chars)

    @property
    def utilization(self) -> float:
        if self.allocated_chars == 0:
            return 0.0
        return self.used_chars / self.allocated_chars


class TokenBudget:
    """Manages the token/character budget for memory injection.

    Budget is measured in characters (≈4 chars per token for English).
    Default: 2,000 chars total (~500 tokens).
    """

    # Default allocation percentages per layer
    DEFAULT_ALLOCATION = {
        1: 0.10,   # Hot Cache: 10%
        2: 0.60,   # Semantic Index: 60%
        3: 0.15,   # Procedural: 15%
        4: 0.10,   # Episodic: 10%
        5: 0.05,   # Reflective: 5%
    }

    LAYER_NAMES = {
        1: "Hot Cache",
        2: "Semantic Index",
        3: "Procedural",
        4: "Episodic",
        5: "Meta/Reflective",
    }

    def __init__(self, max_chars: int = 2000):
        self.max_chars = max_chars
        self.allocations: List[BudgetAllocation] = []

    def allocate(self) -> List[BudgetAllocation]:
        """Distribute budget across layers. Returns allocations."""
        self.allocations = []
        for layer, pct in self.DEFAULT_ALLOCATION.items():
            self.allocations.append(BudgetAllocation(
                layer=layer,
                name=self.LAYER_NAMES[layer],
                allocated_chars=int(self.max_chars * pct),
            ))
        return self.allocations

    def consume(self, layer: int, chars: int) -> bool:
        """Try to consume chars from a layer's budget. Returns True if successful."""
        for alloc in self.allocations:
            if alloc.layer == layer:
                if chars <= alloc.remaining:
                    alloc.used_chars += chars
                    return True
                return False
        return False

    def report(self) -> dict:
        """Generate a budget utilization report."""
        total_used = sum(a.used_chars for a in self.allocations)
        return {
            "max_chars": self.max_chars,
            "total_used": total_used,
            "total_remaining": self.max_chars - total_used,
            "utilization": total_used / self.max_chars if self.max_chars > 0 else 0,
            "layers": [
                {
                    "layer": a.layer,
                    "name": a.name,
                    "allocated": a.allocated_chars,
                    "used": a.used_chars,
                    "remaining": a.remaining,
                    "utilization": a.utilization,
                }
                for a in self.allocations
            ],
        }
