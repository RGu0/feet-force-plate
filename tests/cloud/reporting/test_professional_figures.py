import json
import unittest
from dataclasses import replace

from cloud.analysis.models import ValidationStatus
from tests.cloud.reporting.test_reporting import (
    analysis_run,
    feature_set,
    metric_result,
    report_context,
    service,
)


def complete_metric_results():
    return (
        metric_result(
            metric_id="relative_total_load",
            definition="平均相对总载荷",
            unit="relative_count",
            value_numeric=110.0,
        ),
        metric_result(),
        metric_result(
            metric_id="anterior_posterior_load_balance",
            definition="前后区域相对载荷占比差异",
            unit="%",
            value_numeric=20.0,
        ),
        metric_result(
            metric_id="cop_path_length",
            definition="压力中心轨迹累计路径长度",
            unit="sensor_cell",
            value_numeric=0.7,
        ),
    )


class ProfessionalFigureTests(unittest.TestCase):
    def test_approved_capabilities_add_parameters_and_curves_to_the_same_report(self) -> None:
        report_service, _, _, _ = service()
        features = replace(
            feature_set(),
            mean_sensor_load=tuple(float(index % 64) for index in range(48 * 64)),
        )
        run = replace(
            analysis_run(),
            feature_set=features,
            metric_results=complete_metric_results(),
        )

        document = report_service.publish(run, report_context()).document
        professional = document.to_public_dict()["professional_parameters_and_curves"]

        self.assertEqual(
            [parameter["metric_id"] for parameter in professional["parameters"]],
            ["cop_path_length"],
        )
        self.assertEqual(
            {figure["figure_id"] for figure in professional["curves"]},
            {
                "relative_load_heatmap",
                "total_load_curve",
                "left_right_load_curve",
                "anterior_posterior_load_curve",
                "cop_trajectory",
            },
        )

    def test_curves_are_gated_by_their_approved_metric_capability(self) -> None:
        report_service, _, _, _ = service()
        draft_cop = metric_result(
            metric_id="cop_path_length",
            validation_status=ValidationStatus.DRAFT,
        )
        run = replace(analysis_run(), metric_results=(metric_result(), draft_cop))

        professional = report_service.publish(run, report_context()).document.to_public_dict()[
            "professional_parameters_and_curves"
        ]

        self.assertEqual(professional["parameters"], [])
        self.assertEqual(
            [figure["figure_id"] for figure in professional["curves"]],
            ["left_right_load_curve"],
        )

    def test_every_figure_states_the_real_source_sampling_rate(self) -> None:
        report_service, _, _, _ = service()
        run = replace(
            analysis_run(),
            feature_set=replace(
                feature_set(),
                mean_sensor_load=tuple([1.0] * (48 * 64)),
            ),
            metric_results=complete_metric_results(),
        )

        curves = report_service.publish(run, report_context()).document.to_public_dict()[
            "professional_parameters_and_curves"
        ]["curves"]

        for figure in curves:
            self.assertEqual(figure["source_sample_rate_hz"], 12.0)
            self.assertIn("采集约 12.0 Hz", figure["source_sampling_statement"])
            self.assertIn("显示或连线", figure["source_sampling_statement"])
            self.assertNotIn("display_refresh_hz", figure)

    def test_print_semantics_do_not_depend_on_color_alone(self) -> None:
        report_service, _, _, _ = service()
        run = replace(
            analysis_run(),
            feature_set=replace(
                feature_set(),
                mean_sensor_load=tuple([1.0] * (48 * 64)),
            ),
            metric_results=complete_metric_results(),
        )

        curves = report_service.publish(run, report_context()).document.to_public_dict()[
            "professional_parameters_and_curves"
        ]["curves"]

        for figure in curves:
            self.assertTrue(figure["alt_text"])
            self.assertIn(figure["print_style"], {"grayscale_scale", "line_and_marker"})
            for series in figure["series"]:
                self.assertTrue(series["line_style"])
                self.assertTrue(series["marker"])

    def test_customer_figure_schema_exposes_no_debug_controls_or_quality_details(self) -> None:
        report_service, _, _, _ = service()
        run = replace(
            analysis_run(),
            feature_set=replace(
                feature_set(),
                mean_sensor_load=tuple([1.0] * (48 * 64)),
            ),
            metric_results=complete_metric_results(),
        )

        serialized = json.dumps(
            report_service.publish(run, report_context()).document.to_public_dict(),
            ensure_ascii=False,
        )

        for forbidden in (
            "debug_control",
            "internal_quality",
            "data_confidence_limitations",
            "failure_stack",
            "raw_pressure_payload",
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
