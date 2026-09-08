# Deliverables

Three audience-specific Word documents, generated from real `eda/outputs/` data (numbers
and charts trace back to the EDA scripts, nothing is hand-typed/illustrative):

| File | Audience | Content |
|---|---|---|
| `Sales_Briefing.docx` | Sales / Business Development | Business problem, plain-language explanation, real evidence charts, differentiators, customer talking points, honest status, glossary |
| `Domain_Expert_Briefing.docx` | Wind turbine O&M / reliability engineers | Real dataset stats, fault taxonomy from real maintenance logs, per-asset detection methodology with evidence charts for all 7 components (including vibration-based bearing analysis), ML approach, honest data-quality limitations |
| `Developer_Setup_Guide.docx` | Developers | Prerequisites, one-script setup, step-by-step instructions, troubleshooting |

## Regenerating

Each `.docx` is produced by a script under `scripts/` and can be regenerated any time the
underlying EDA data changes (re-run `eda/scripts/*.py` first, then these):

```powershell
python scripts/generate_sales_briefing.py
python scripts/generate_domain_expert_briefing.py
python scripts/generate_developer_guide.py
```

Requires `python-docx` (`pip install python-docx`). `_docx_style.py` holds the shared
visual identity (fonts, colors, table/callout/chart helpers); `_data.py` loads the real
numbers from `eda/outputs/`.

## Visually QA-ing a regenerated doc

Word reflows text automatically, but always spot-check a regenerated doc for overflowing
images/tables or bad page breaks before treating it as final - `_word_qa.py` renders every
page to PNG (via Word COM → PDF → PyMuPDF) so you can actually look at them:

```powershell
python scripts/_word_qa.py Sales_Briefing.docx
```

Requires `pywin32` and `pymupdf`, and Microsoft Word installed. Outputs a `.pdf` next to
the source file and a `<name>_qa_pages/page_NN.png` per page - both are gitignored, delete
them once you're satisfied.
