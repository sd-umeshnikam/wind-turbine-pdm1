"""Generates docs/deliverables/Developer_Setup_Guide.docx.

Audience: developers setting up the platform locally on Windows. Mirrors
docs/DEVELOPER_SETUP.md but as a polished, step-by-step Word deliverable with real
command examples - every command here has actually been run successfully against
this repo (see the session that built scripts/setup-*.ps1).
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _docx_style as s

OUT_PATH = Path(__file__).resolve().parents[1] / "Developer_Setup_Guide.docx"


def build() -> None:
    doc = s.new_document()

    s.add_title_page(
        doc,
        "Developer Setup & Installation Guide",
        "Wind Turbine Predictive Maintenance Platform — Local Environment Setup (Windows)",
        [
            "Prepared by: Data Engineering & Data Science Team",
            f"Date: {datetime.date.today().isoformat()}",
            "Audience: Developers",
            "Classification: Internal",
        ],
    )

    s.add_heading(doc, "In This Guide", 1)
    s.add_bullets(doc, [
        "Prerequisites and how to verify them",
        "The fastest path: one script sets everything up",
        "Step-by-step instructions for each piece (EDA, backend services, frontend)",
        "What a successful setup looks like",
        "Going further: deploying to real AWS/Databricks environments",
        "Troubleshooting",
    ])
    s.add_callout(doc, "SCOPE",
        "This guide covers only the local, no-AWS-account-needed pieces (EDA, backend "
        "service tests, frontend dashboard). Deploying to real AWS/Databricks environments "
        "is covered separately in infra/terraform/README.md and "
        "docs/manual-setup/RUNBOOK.md.", kind="note")
    s.add_page_break(doc)

    # 1. Prerequisites --------------------------------------------------------
    s.add_heading(doc, "1. Prerequisites", 1)
    s.add_table(
        doc,
        ["Tool", "Minimum version", "Check with", "Get it from"],
        [
            ["Python", "3.10+", "python --version", "python.org/downloads (check \"Add to PATH\")"],
            ["Node.js (incl. npm)", "18 LTS+", "node --version / npm --version", "nodejs.org"],
            ["Git", "any recent", "git --version", "git-scm.com/download/win"],
            ["PowerShell", "5.1+ (ships with Windows)", "$PSVersionTable.PSVersion", "already installed"],
        ],
        widths=[1.6, 1.8, 2.0, 1.8],
    )
    s.add_body(doc,
        "You do not need an AWS account, Databricks workspace, or Terraform CLI for local "
        "setup - those are only needed if you go on to actually deploy something (§5)."
    )
    s.add_callout(doc, "NOTE",
        "If this repo lives inside a path with spaces (e.g. a company OneDrive folder), "
        "that's fine - every script here quotes paths correctly. Run these scripts from "
        "inside the repo folder rather than passing long absolute paths around by hand.",
        kind="note")

    # 2. Fastest path -----------------------------------------------------------
    s.add_heading(doc, "2. Fastest Path: Run Everything With One Script", 1)
    s.add_body(doc, "From the repo root, in PowerShell:")
    s.add_code_block(doc, [".\\scripts\\setup-all.ps1"])
    s.add_body(doc,
        "Or double-click scripts\\setup.bat in File Explorer if you'd rather not open a "
        "terminal - it runs the same script with a relaxed execution policy for just that "
        "one run (see §6 if you hit an execution-policy error running the .ps1 directly)."
    )
    s.add_body(doc, "This will, in order:")
    s.add_numbered(doc, [
        "Verify Python/Node/npm are on PATH (fails fast with a clear message if not).",
        "Install pandas/matplotlib/numpy/pyarrow and run all 5 EDA scripts against the "
        "real SCADA CSVs in ../wind-turbine-scada-data-for-early-fault-detection/ (sibling "
        "folder).",
        "npm install && npm test for each of the 5 backend Lambda services under services/.",
        "npm install && npm run build for the React dashboard under frontend/dashboard-app/.",
    ])
    s.add_body(doc,
        "Expect this to take a few minutes the first time (Farm C's EDA read is the "
        "slowest single step, ~2-3 minutes) and much faster on repeat runs."
    )
    s.add_body(doc, "Flags, if you want to skip a piece:")
    s.add_code_block(doc, [
        ".\\scripts\\setup-all.ps1 -SkipEda          # skip if eda/outputs/ is already populated",
        ".\\scripts\\setup-all.ps1 -SkipServices     # skip backend service install/test",
        ".\\scripts\\setup-all.ps1 -SkipFrontend     # skip frontend install/build",
    ])

    # 3. Step by step -------------------------------------------------------
    s.add_heading(doc, "3. Step-by-Step: Each Piece Individually", 1)

    s.add_heading(doc, "3.1 EDA", 2)
    s.add_body(doc,
        "Regenerates every chart and number in eda/EDA_REPORT.md from the real CSVs:"
    )
    s.add_code_block(doc, [
        ".\\scripts\\setup-eda.ps1",
        "# or, if pandas/matplotlib/numpy/pyarrow are already installed:",
        ".\\scripts\\setup-eda.ps1 -SkipInstall",
    ])
    s.add_body(doc,
        "Outputs land in eda/outputs/ (JSON/CSV data) and eda/outputs/charts/ (PNGs). Open "
        "eda/EDA_REPORT.md in any Markdown viewer to see the findings with charts embedded."
    )

    s.add_heading(doc, "3.2 Backend Services", 2)
    s.add_body(doc, "Install and test all five services, or just one:")
    s.add_code_block(doc, [
        ".\\scripts\\setup-services.ps1",
        ".\\scripts\\setup-services.ps1 -Only telemetry-api",
    ])
    s.add_body(doc,
        "Each service under services/<name>/ is independent (own package.json, own "
        "tests) - read services/telemetry-api/README.md first, it's the fully-built "
        "reference the other four follow."
    )

    s.add_heading(doc, "3.3 Frontend Dashboard", 2)
    s.add_body(doc, "Build a production bundle, or run the dev server:")
    s.add_code_block(doc, [
        ".\\scripts\\setup-frontend.ps1          # production build -> frontend/dashboard-app/dist",
        ".\\scripts\\setup-frontend.ps1 -Dev     # dev server at http://localhost:5173",
    ])
    s.add_body(doc,
        "The dashboard runs entirely against realistic mock data matching the real GraphQL "
        "schema when VITE_APPSYNC_URL isn't set (see "
        "frontend/dashboard-app/src/api/client.ts), so -Dev gives a fully click-through "
        "app with zero AWS setup."
    )

    # 4. What done looks like -------------------------------------------------
    s.add_heading(doc, "4. What \"Done\" Looks Like", 1)
    s.add_body(doc, "After setup-all.ps1 finishes without errors, you should have:")
    s.add_bullets(doc, [
        "eda/outputs/charts/*.png - 17 chart images, plus eda/outputs/*.json / *.csv",
        "services/*/dist/ and green test output for all 5 services",
        "frontend/dashboard-app/dist/index.html plus built JS/CSS assets",
    ])
    s.add_body(doc,
        "If you then run .\\scripts\\setup-frontend.ps1 -Dev and open "
        "http://localhost:5173, you should see the Fleet Overview page with real numbers "
        "(36 turbines, 44 anomaly / 51 normal events) and be able to navigate to Asset "
        "Detail, Digital Twin (a rotating 3D turbine), Forecasts/RUL, and Alerts."
    )

    # 5. Going further -----------------------------------------------------
    s.add_heading(doc, "5. Going Further: Deploying to Real AWS/Databricks", 1)
    s.add_body(doc, "This local setup does not touch any cloud account. Once ready to deploy:")
    s.add_bullets(doc, [
        "Read docs/architecture/BLUEPRINT.md first - the full architecture and why it's "
        "built this way.",
        "Terraform path: infra/terraform/README.md - needs the Terraform CLI, an AWS "
        "account (or three, one per environment - see ADR-0001), and a Databricks account.",
        "Manual console path: docs/manual-setup/RUNBOOK.md - click-ops equivalent, also "
        "useful for the one-time account/SSO bootstrap even if Terraform is used for "
        "everything after.",
        "Data platform: data-platform/README.md - deploying the Databricks Asset Bundle "
        "(databricks bundle deploy) once a workspace exists.",
    ])

    # 6. Troubleshooting -----------------------------------------------------
    s.add_page_break(doc)
    s.add_heading(doc, "6. Troubleshooting", 1)
    s.add_table(
        doc,
        ["Symptom", "Cause", "Fix"],
        [
            ["\"running scripts is disabled on this system\"",
             "PowerShell execution policy blocks local scripts",
             "Double-click scripts\\setup.bat instead, or run "
             "Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass once per session, "
             "then re-run the .ps1 in that same terminal."],
            ["'python' / 'node' not found on PATH",
             "Tool installed without PATH update, or terminal opened before install",
             "Reinstall with \"Add to PATH\" checked, then close and reopen the terminal."],
            ["EDA script can't find the raw CSVs",
             "Repo cloned somewhere the sibling data folder doesn't exist",
             "Move the repo so ../wind-turbine-scada-data-for-early-fault-detection/ "
             "exists alongside it, or edit the paths in eda/scripts/_common.py."],
            ["npm install is slow / reports vulnerabilities",
             "Expected npm audit warnings on a fresh scaffold with pinned starter versions",
             "Don't run npm audit fix --force reflexively - review changes first, "
             "especially for Lambda services where a major SDK bump could change API shape."],
            ["File lock / one-off install error",
             "OneDrive sync briefly locking a file mid-install (if repo is OneDrive-synced)",
             "Re-run the command - it almost always succeeds on retry. Pausing OneDrive "
             "sync during heavy local dev avoids it entirely."],
            ["Port 5173 already in use",
             "Another Vite dev server is already running",
             "Stop it, or note the alternate port (5174, 5175, ...) Vite picks and shown "
             "in its terminal output."],
        ],
        widths=[1.8, 2.2, 2.9],
    )

    doc.save(str(OUT_PATH))
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    build()
