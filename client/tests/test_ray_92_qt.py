from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QPushButton

from client.app.pages import PageId
from client.app.qt_shell import ScreeningWindow


def test_subject_page_exposes_id_types_and_lookup_action(qtbot) -> None:
    actions: list[str] = []
    window = ScreeningWindow(on_action=actions.append)
    qtbot.addWidget(window)
    page = window.page_widget(PageId.SUBJECT_IDENTIFICATION)
    id_type = page.findChild(QComboBox, "subjectIdTypeInput")
    lookup = page.findChild(QPushButton, "lookupSubjectButton")

    assert id_type.count() == 4
    assert {id_type.itemData(index) for index in range(id_type.count())} == {
        "institution_record",
        "medical_record_number",
        "examination_number",
        "resident_number",
    }
    qtbot.mouseClick(lookup, Qt.MouseButton.LeftButton)
    assert actions == ["LOOKUP_SUBJECT"]


def test_profile_fields_each_have_an_explicit_missing_state_selector(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    page = window.page_widget(PageId.PROFILE)
    expected_states = {
        "PROVIDED",
        "NONE_REPORTED",
        "UNKNOWN",
        "DECLINED",
        "NOT_APPLICABLE",
    }

    for field_name in (
        "ageBand",
        "sex",
        "height",
        "weight",
        "conditionTags",
        "injuryTags",
    ):
        selector = page.findChild(QComboBox, f"{field_name}State")
        assert selector is not None
        assert {
            selector.itemData(index) for index in range(selector.count())
        } == expected_states


def test_consent_choices_are_separate_and_not_preselected(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    page = window.page_widget(PageId.CONSENT)
    required = page.findChild(QCheckBox, "requiredConsent")
    research = page.findChild(QCheckBox, "researchConsent")

    assert not required.isChecked()
    assert not research.isChecked()
