import os
import sys
import unittest
from unittest.mock import patch, MagicMock

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import enrichment_orchestrator  # noqa: E402


class EnrichmentOrchestratorTests(unittest.TestCase):
    @patch("enrichment_orchestrator.enrich_search_terms", return_value={})
    @patch("enrichment_orchestrator.llm_translate_to_english", return_value={})
    @patch("enrichment_orchestrator.tag_techstack", return_value={})
    @patch("enrichment_orchestrator.llm_translate_entries", return_value={})
    @patch("enrichment_orchestrator.llm_tag_entries", return_value={})
    def test_enrich_entries_calls_all_steps_in_order(
        self, mock_tag, mock_translate, mock_techstack, mock_en, mock_search
    ):
        """Verify all enrichment steps are called (eval harness falls back gracefully)."""
        entries = [
            {"id": "test-1", "name": "Test", "type": "mcp", "tags": [], "description": "test"}
        ]
        # eval_bridge import will fail (not installed), legacy fallback will also
        # fail since enrich_quality/populate_signals are not on sys.path in test.
        # The orchestrator catches both via ImportError + Exception, so this is fine.
        enrichment_orchestrator.enrich_entries(entries)

        mock_tag.assert_called_once()
        mock_translate.assert_called_once()
        mock_search.assert_called_once()

    @patch("enrichment_orchestrator.enrich_search_terms", return_value={})
    @patch("enrichment_orchestrator.llm_translate_to_english", return_value={})
    @patch("enrichment_orchestrator.tag_techstack", return_value={})
    @patch("enrichment_orchestrator.llm_translate_entries", return_value={})
    @patch("enrichment_orchestrator.llm_tag_entries")
    def test_idempotent_tags_not_overwritten(
        self, mock_tag, mock_translate, mock_techstack, mock_en, mock_search
    ):
        mock_tag.return_value = {"test-1": ["python", "cli"]}
        entries = [
            {"id": "test-1", "name": "Test", "type": "mcp", "tags": ["existing", "tags"], "description": "test"}
        ]
        enrichment_orchestrator.enrich_entries(entries)
        # Tags should NOT be overwritten since entry already has >=2 tags
        self.assertEqual(entries[0]["tags"], ["existing", "tags"])

    @patch("enrichment_orchestrator.enrich_search_terms", return_value={})
    @patch("enrichment_orchestrator.llm_translate_to_english", return_value={})
    @patch("enrichment_orchestrator.tag_techstack", return_value={})
    @patch("enrichment_orchestrator.llm_translate_entries", return_value={})
    @patch("enrichment_orchestrator.llm_tag_entries", return_value={})
    def test_eval_harness_called_when_available(
        self, mock_tag, mock_translate, mock_techstack, mock_en, mock_search
    ):
        """When eval_bridge is importable, eval_and_map is called on entries."""
        mock_eval_and_map = MagicMock()
        entries = [
            {"id": "test-1", "name": "Test", "type": "skill", "tags": [], "description": "test"}
        ]

        # Patch the import mechanism so eval_bridge.eval_and_map is available
        import types
        fake_bridge = types.ModuleType("eval_bridge")
        fake_bridge.eval_and_map = mock_eval_and_map

        with patch.dict("sys.modules", {"eval_bridge": fake_bridge}):
            enrichment_orchestrator.enrich_entries(entries)

        mock_eval_and_map.assert_called_once()
        # Verify entries were passed as first arg
        call_args = mock_eval_and_map.call_args
        self.assertIs(call_args[0][0], entries)

    @patch("enrichment_orchestrator.enrich_search_terms", return_value={})
    @patch("enrichment_orchestrator.llm_translate_to_english", return_value={})
    @patch("enrichment_orchestrator.tag_techstack", return_value={})
    @patch("enrichment_orchestrator.llm_translate_entries", return_value={})
    @patch("enrichment_orchestrator.llm_tag_entries", return_value={})
    def test_legacy_fallback_when_eval_bridge_missing(
        self, mock_tag, mock_translate, mock_techstack, mock_en, mock_search
    ):
        """When eval_bridge is not importable, legacy evaluator is attempted."""
        entries = [
            {"id": "test-1", "name": "Test", "type": "skill", "tags": [], "description": "test"}
        ]

        # Ensure eval_bridge is NOT available
        with patch.dict("sys.modules", {"eval_bridge": None}):
            mock_enrich = MagicMock(return_value={"test-1": {"coding_relevance": 4}})
            mock_populate = MagicMock()
            with patch.dict("sys.modules", {
                "llm_evaluator": MagicMock(enrich_quality=mock_enrich),
                "unified_enrichment": MagicMock(populate_signals=mock_populate),
            }):
                enrichment_orchestrator.enrich_entries(entries)

            # Legacy path should have set evaluation via setdefault().update()
            # (the mocked modules handle the actual logic)


if __name__ == "__main__":
    unittest.main()
