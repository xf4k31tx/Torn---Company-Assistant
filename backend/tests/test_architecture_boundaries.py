from pathlib import Path


def test_web_core_has_no_desktop_or_google_integration_imports() -> None:
    source_root = Path(__file__).parents[1] / "src" / "tca_web"
    forbidden = (
        "import tkinter",
        "from tkinter",
        "import gspread",
        "googleapiclient",
        "google.auth",
        "SheetsClient",
    )
    violations = {
        str(path.relative_to(source_root)): token
        for path in source_root.rglob("*.py")
        for token in forbidden
        if token in path.read_text(encoding="utf-8")
    }
    assert violations == {}
