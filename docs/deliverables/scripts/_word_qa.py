"""Visual QA helper: renders a .docx to PNG pages (via Word COM -> PDF -> PyMuPDF)
so layout issues (overflowing images/tables, bad page breaks) can actually be seen,
the same way the platform's .pptx deliverables are QA'd via PowerPoint COM export.

Usage: python _word_qa.py <path-to-docx>
Outputs: <docx>.pdf next to the source file, and <stem>_qa_pages/page_NN.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf
import win32com.client


def docx_to_pdf(docx_path: Path, pdf_path: Path) -> None:
    word = win32com.client.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(str(docx_path))
        try:
            doc.SaveAs2(str(pdf_path), FileFormat=17)  # wdFormatPDF
        finally:
            doc.Close(False)
    finally:
        word.Quit()


def pdf_to_pngs(pdf_path: Path, out_dir: Path, dpi: int = 110) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("page_*.png"):
        old.unlink()
    pdf = pymupdf.open(str(pdf_path))
    zoom = dpi / 72
    mat = pymupdf.Matrix(zoom, zoom)
    paths = []
    for i, page in enumerate(pdf):
        pix = page.get_pixmap(matrix=mat)
        out = out_dir / f"page_{i + 1:02d}.png"
        pix.save(str(out))
        paths.append(out)
    pdf.close()
    return paths


def main() -> None:
    docx_path = Path(sys.argv[1]).resolve()
    pdf_path = docx_path.with_suffix(".pdf")
    out_dir = docx_path.parent / f"{docx_path.stem}_qa_pages"

    print(f"Exporting {docx_path.name} -> PDF via Word COM...")
    docx_to_pdf(docx_path, pdf_path)

    print(f"Rendering PDF pages -> PNG ({out_dir})...")
    pages = pdf_to_pngs(pdf_path, out_dir)
    print(f"Rendered {len(pages)} pages.")
    for p in pages:
        print(f"  {p}")


if __name__ == "__main__":
    main()
