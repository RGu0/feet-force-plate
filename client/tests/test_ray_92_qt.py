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


def test_profile_condition_chips_are_selectable_and_persist_their_state(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    page = window.page_widget(PageId.PROFILE)
    chips = {
        button.text(): button
        for button in page.findChildren(QPushButton)
        if button.property("profileChip")
    }

    assert set(chips) == {
        "高血压",
        "糖尿病",
        "既往下肢损伤",
        "关节炎",
        "周围神经病变",
        "足部手术史",
        "未提供",
    }
    assert all(button.height() == 40 for button in chips.values())

    qtbot.mouseClick(chips["糖尿病"], Qt.MouseButton.LeftButton)
    qtbot.mouseClick(chips["足部手术史"], Qt.MouseButton.LeftButton)

    assert chips["糖尿病"].isChecked()
    assert chips["足部手术史"].isChecked()
    assert window.profile_form_values()["conditionTags"] == (
        "PROVIDED",
        "糖尿病,足部手术史",
    )

    qtbot.mouseClick(chips["未提供"], Qt.MouseButton.LeftButton)

    assert chips["未提供"].isChecked()
    assert not chips["糖尿病"].isChecked()
    assert not chips["足部手术史"].isChecked()
    assert window.profile_form_values()["conditionTags"] == (
        "NONE_REPORTED",
        "",
    )

    qtbot.mouseClick(chips["高血压"], Qt.MouseButton.LeftButton)

    assert chips["高血压"].isChecked()
    assert not chips["未提供"].isChecked()
    assert window.profile_form_values()["conditionTags"] == (
        "PROVIDED",
        "高血压",
    )


def test_consent_choices_are_separate_and_not_preselected(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    page = window.page_widget(PageId.CONSENT)
    required = page.findChild(QCheckBox, "requiredConsent")
    research = page.findChild(QCheckBox, "researchConsent")

    assert not required.isChecked()
    assert not research.isChecked()
