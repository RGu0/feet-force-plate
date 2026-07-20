from __future__ import annotations

import unittest

from client.app.pages import PAGE_DEFINITIONS, PageId, page_for_step
from client.workflow.state_machine import ScreeningStep


class PageCatalogTests(unittest.TestCase):
    def test_catalog_contains_all_prd_pages_with_single_primary_action(self) -> None:
        self.assertEqual(set(PAGE_DEFINITIONS), set(PageId))
        self.assertEqual(len(PAGE_DEFINITIONS), 11)
        for definition in PAGE_DEFINITIONS.values():
            self.assertLessEqual(len(definition.primary_actions), 1, definition.page_id)

    def test_workflow_steps_route_to_the_prd_page(self) -> None:
        self.assertEqual(page_for_step(ScreeningStep.HOME), PageId.WORKBENCH)
        self.assertEqual(
            page_for_step(ScreeningStep.SUBJECT_IDENTIFICATION),
            PageId.SUBJECT_IDENTIFICATION,
        )
        self.assertEqual(page_for_step(ScreeningStep.PROFILE_DETAILS), PageId.PROFILE)
        self.assertEqual(
            page_for_step(ScreeningStep.CONSENT_CONFIRMATION),
            PageId.CONSENT,
        )
        self.assertEqual(page_for_step(ScreeningStep.PREFLIGHT), PageId.PREFLIGHT)
        self.assertEqual(
            page_for_step(ScreeningStep.POSITION_GUIDANCE),
            PageId.POSITION_GUIDANCE,
        )
        self.assertEqual(page_for_step(ScreeningStep.ACQUIRING), PageId.ACQUIRING)
        self.assertEqual(page_for_step(ScreeningStep.FINALIZING), PageId.RESULT)
        self.assertEqual(page_for_step(ScreeningStep.BASIC_REPORT), PageId.RESULT)

    def test_acquiring_page_has_one_stop_action_and_no_navigation(self) -> None:
        acquiring = PAGE_DEFINITIONS[PageId.ACQUIRING]

        self.assertEqual(acquiring.primary_actions, ())
        self.assertEqual(acquiring.secondary_actions, ("STOP_SCREENING",))
        self.assertFalse(acquiring.global_navigation_enabled)


if __name__ == "__main__":
    unittest.main()
