"""Two rules about the service code itself (spec 5.3)."""

import ast
import re
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent.parent
MODULES = sorted(p for p in SERVICE_DIR.glob("*.py"))
NAMES = re.compile(
    r"et0_fao_evapotranspiration|precipitation_sum|daily_units|utc_offset_seconds|forecast_days|\bdaily\b"
)


def test_the_modules_were_found() -> None:
    assert {"main.py", "provider.py", "forecast_service.py"} <= {p.name for p in MODULES}


def test_open_meteo_names_appear_only_in_provider_py() -> None:
    offenders = [p.name for p in MODULES if p.name != "provider.py" and NAMES.search(p.read_text())]
    assert offenders == []
    assert NAMES.search((SERVICE_DIR / "provider.py").read_text())  # the rule looks at the right names


def test_no_module_refers_to_the_registry_service() -> None:
    offenders = []
    for path in MODULES:
        text = path.read_text()
        imports = [
            n.module or "" if isinstance(n, ast.ImportFrom) else a.name
            for n in ast.walk(ast.parse(text))
            if isinstance(n, (ast.Import, ast.ImportFrom))
            for a in (getattr(n, "names", None) or [None])
        ]
        if re.search(r"registry", text, re.IGNORECASE) or any("registry" in i for i in imports):
            offenders.append(path.name)
    assert offenders == []
