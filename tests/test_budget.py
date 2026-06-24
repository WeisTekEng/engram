

class TestTokenBudget:
    """Phase 3: Per-layer token budget isolation."""

    def test_layer5_rejected_when_budget_exhausted(self):
        """Layer 5 item rejected when L5 pool exhausted, even if L2 pool has room."""
        from engram.core import RecallResult
        from engram.utils.token_budget import TokenBudget

        budget = TokenBudget(max_chars=200)
        result = RecallResult()
        # Label "[0.90] AAAAAAAAAAAA (reflection)" ≈ 37 chars > L5's 10 char pool
        result.unified = [
            {"content": "A" * 12, "score": 0.9, "layer": "reflection", "category": "insight", "importance": 1.0},
        ]

        formatted = result.format_for_prompt(budget)
        assert "Relevant Memories" not in formatted, (
            f"L5 item should be rejected when L5 budget exhausted. Got: {formatted[:100]}"
        )

    def test_layer2_isolated_from_other_layers(self):
        """Layer 2 item rejected when L2 pool exhausted, other layers' room doesn't help."""
        from engram.core import RecallResult
        from engram.utils.token_budget import TokenBudget

        budget = TokenBudget(max_chars=150)
        result = RecallResult()
        # First L2 item fits, second exceeds remaining L2 budget
        result.unified = [
            {"content": "X" * 40, "score": 0.9, "layer": "memory (general)", "category": "general", "importance": 0.5},
            {"content": "Y" * 40, "score": 0.8, "layer": "memory (general)", "category": "general", "importance": 0.4},
        ]

        formatted = result.format_for_prompt(budget)
        lines = formatted.split("\n")
        relevant_lines = [l for l in lines if l.startswith("- [0.")]
        assert len(relevant_lines) == 1, (
            f"Expected 1 L2 item, got {len(relevant_lines)}: {relevant_lines}"
        )

    def test_layer3_uses_correct_budget(self):
        """Procedural (L3) items consume from L3's 15% pool, not L2's 60%."""
        from engram.core import RecallResult
        from engram.utils.token_budget import TokenBudget

        budget = TokenBudget(max_chars=200)
        # L3 has 30 chars; L2 has 120 chars
        result = RecallResult()
        # L2 item takes most of L2 budget, L3 item should NOT borrow from L2
        result.unified = [
            {"content": "A" * 90, "score": 1.0, "layer": "memory (general)", "category": "general", "importance": 0.9},
            {"content": "Skill workflow", "score": 0.9, "layer": "procedural", "category": "skill", "importance": 0.8},
        ]

        formatted = result.format_for_prompt(budget)
        # L3 label "[0.90] Skill workflow (procedural)" ≈ 41 chars > L3's 30
        # If it incorrectly uses L2 budget (13 chars left), it would fit
        assert "procedural" not in formatted, (
            f"L3 item should use L3 budget (30 chars, 41 needed) not L2's. Got: {formatted[:200]}"
        )

    def test_layer4_budget_separate_from_layer2(self):
        """Episodic (L4) items consume from L4's 10% pool."""
        from engram.core import RecallResult
        from engram.utils.token_budget import TokenBudget

        budget = TokenBudget(max_chars=200)
        result = RecallResult()
        result.unified = [
            {"content": "OK", "score": 0.95, "layer": "episodic", "category": "session", "importance": 0.7},
        ]

        formatted = result.format_for_prompt(budget)
        assert "episodic" in formatted, (
            f"Small L4 item should fit in L4 budget. Got: {formatted[:200]}"
        )

    def test_budget_report_shows_per_layer_usage(self):
        """After format_for_prompt, budget report shows usage spread across layers."""
        from engram.core import RecallResult
        from engram.utils.token_budget import TokenBudget

        budget = TokenBudget(max_chars=500)
        result = RecallResult()
        result.unified = [
            {"content": "Semantic fact A", "score": 0.9, "layer": "memory (general)", "category": "general", "importance": 0.5},
            {"content": "Workflow step B", "score": 0.85, "layer": "procedural", "category": "skill", "importance": 0.7},
            {"content": "Session event C", "score": 0.8, "layer": "episodic", "category": "session", "importance": 0.6},
        ]

        result.format_for_prompt(budget)
        report = budget.report()

        used_layers = {l["layer"] for l in report["layers"] if l["used"] > 0}
        assert 2 in used_layers, f"Layer 2 should have usage, got: {used_layers}"
        assert 3 in used_layers, f"Layer 3 should have usage, got: {used_layers}"
        assert 4 in used_layers, f"Layer 4 should have usage, got: {used_layers}"
        l2_used = [l["used"] for l in report["layers"] if l["layer"] == 2][0]
        total_used = report["total_used"]
        assert l2_used < total_used, (
            f"Layer 2 has {l2_used} of {total_used} total — usage should be spread across layers"
        )
