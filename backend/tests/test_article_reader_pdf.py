"""Real PDF bytes protect the reader contract when upgrading the parser."""

import pytest

from app.services.article_reader import ArticleReaderError, _extract_from_pdf


def _pdf_bytes(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Title (Reader compatibility report) >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, content in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode() + content + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R /Info 6 0 R >>\n" f"startxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)


def test_pdf_reader_preserves_text_title_and_source():
    text = "This research report contains enough readable text for the article reader to preserve its content."
    source = "https://example.com/report.pdf"

    article = _extract_from_pdf(_pdf_bytes(text), source)

    assert article.title == "Reader compatibility report"
    assert article.text_content == text
    assert article.canonical_url == source
    assert article.extraction_method == "pdf"
    assert article.content_blocks == [{"type": "paragraph", "text": text}]


@pytest.mark.parametrize("payload", [b"not a PDF file", _pdf_bytes("")], ids=["invalid", "no-text"])
def test_unreadable_pdf_falls_back_to_original_link(payload):
    with pytest.raises(ArticleReaderError) as error:
        _extract_from_pdf(payload, "https://example.com/unreadable.pdf")

    assert error.value.code == "not_readerable"
