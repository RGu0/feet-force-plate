from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from client.workflow.state_machine import ScreeningStep


class PageId(StrEnum):
    WORKBENCH = "P-01"
    SUBJECT_IDENTIFICATION = "P-02"
    PROFILE = "P-03"
    CONSENT = "P-04"
    PREFLIGHT = "P-05"
    POSITION_GUIDANCE = "P-06"
    ACQUIRING = "P-07"
    RESULT = "P-08"
    RECORDS = "P-09"
    REPORT_PREVIEW = "P-10"
    SUPPORT = "P-11"


@dataclass(frozen=True, slots=True)
class PageDefinition:
    page_id: PageId
    title: str
    primary_actions: tuple[str, ...]
    secondary_actions: tuple[str, ...] = ()
    global_navigation_enabled: bool = True


PAGE_DEFINITIONS = {
    PageId.WORKBENCH: PageDefinition(
        PageId.WORKBENCH,
        "足底压力健康筛查",
        ("START_NEW_SCREENING",),
    ),
    PageId.SUBJECT_IDENTIFICATION: PageDefinition(
        PageId.SUBJECT_IDENTIFICATION,
        "受试者信息",
        ("CONFIRM_SUBJECT",),
        ("CREATE_ANONYMOUS_SUBJECT",),
    ),
    PageId.PROFILE: PageDefinition(
        PageId.PROFILE,
        "基础信息（选填，可直接继续）",
        ("SAVE_PROFILE",),
        ("SKIP_PROFILE",),
    ),
    PageId.CONSENT: PageDefinition(
        PageId.CONSENT,
        "数据使用说明",
        ("CONFIRM_CONSENT",),
    ),
    PageId.PREFLIGHT: PageDefinition(
        PageId.PREFLIGHT,
        "正在准备检测",
        (),
        ("RECHECK",),
        False,
    ),
    PageId.POSITION_GUIDANCE: PageDefinition(
        PageId.POSITION_GUIDANCE,
        "请站到压力垫中央",
        ("START_ACQUISITION",),
        (),
        False,
    ),
    PageId.ACQUIRING: PageDefinition(
        PageId.ACQUIRING,
        "检测进行中",
        (),
        ("STOP_SCREENING",),
        False,
    ),
    PageId.RESULT: PageDefinition(
        PageId.RESULT,
        "检测结果",
        ("VIEW_BASIC_REPORT",),
        ("START_NEXT_SCREENING", "RETRY_SCREENING"),
    ),
    PageId.RECORDS: PageDefinition(
        PageId.RECORDS,
        "检测记录",
        ("VIEW_SELECTED_REPORT",),
    ),
    PageId.REPORT_PREVIEW: PageDefinition(
        PageId.REPORT_PREVIEW,
        "报告预览",
        ("EXPORT_PDF",),
        ("PRINT_REPORT",),
    ),
    PageId.SUPPORT: PageDefinition(
        PageId.SUPPORT,
        "设备与支持",
        ("RECHECK_SYSTEM",),
        ("EXPORT_DIAGNOSTIC",),
    ),
}


_STEP_TO_PAGE = {
    ScreeningStep.HOME: PageId.WORKBENCH,
    ScreeningStep.SUBJECT_IDENTIFICATION: PageId.SUBJECT_IDENTIFICATION,
    ScreeningStep.PROFILE_DETAILS: PageId.PROFILE,
    ScreeningStep.CONSENT_CONFIRMATION: PageId.CONSENT,
    ScreeningStep.PREFLIGHT: PageId.PREFLIGHT,
    ScreeningStep.POSITION_GUIDANCE: PageId.POSITION_GUIDANCE,
    ScreeningStep.ACQUIRING: PageId.ACQUIRING,
    ScreeningStep.FINALIZING: PageId.RESULT,
    ScreeningStep.BASIC_REPORT: PageId.RESULT,
    ScreeningStep.RETRY_REQUIRED: PageId.RESULT,
    ScreeningStep.INCOMPLETE: PageId.RESULT,
    ScreeningStep.FAILED: PageId.RESULT,
}


def page_for_step(step: ScreeningStep) -> PageId:
    return _STEP_TO_PAGE[step]
