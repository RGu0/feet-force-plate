from __future__ import annotations

import json
import textwrap

from cloud.reporting.models import ReportDocument


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class MinimalPdfRenderer:
    """Deterministic dependency-free reference renderer.

    Production must replace this port with the approved embedded-font renderer and pass
    visual/print validation. This implementation creates a valid immutable PDF artifact
    suitable for contract tests without claiming Chinese typography compliance.
    """

    renderer_version = "minimal-pdf/1"
    template_version = "cloud-report/1"

    def render(self, document: ReportDocument) -> bytes:
        canonical = json.dumps(
            document.to_public_dict(),
            ensure_ascii=True,
            sort_keys=False,
            separators=(",", ":"),
        )
        lines = ["FeetForcePlate Cloud Complete Report"]
        lines.extend(textwrap.wrap(canonical, width=88, break_long_words=True))
        text_commands = ["BT", "/F1 8 Tf", "40 800 Td"]
        for index, line in enumerate(lines[:52]):
            if index:
                text_commands.append("0 -14 Td")
            text_commands.append(f"({_escape_pdf_text(line)}) Tj")
        text_commands.append("ET")
        stream = "\n".join(text_commands).encode("ascii")

        objects = (
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
            ),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream",
        )
        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, body in enumerate(objects, start=1):
            offsets.append(len(output))
            output.extend(f"{number} 0 obj\n".encode("ascii"))
            output.extend(body)
            output.extend(b"\nendobj\n")
        xref_offset = len(output)
        output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.extend(
            (
                f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n"
            ).encode("ascii")
        )
        return bytes(output)
