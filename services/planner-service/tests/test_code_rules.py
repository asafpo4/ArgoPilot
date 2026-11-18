import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_MODULES = {"time", "os", "random", "httpx", "fastapi"}


def test_engine_is_pure():
    tree = ast.parse((ROOT / "engine.py").read_text())
    stdlib = set(sys.stdlib_module_names)
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in engine.py"
            modules = [node.module or ""]
        for module in modules:
            top = module.split(".")[0]
            assert top in stdlib, f"engine.py imports non-standard module {top}"
            assert top not in FORBIDDEN_MODULES, f"engine.py imports {top}"
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            assert name not in {"today", "now"}, f"engine.py calls {name}()"
        if isinstance(node, ast.Attribute):
            assert not (
                node.attr in {"environ", "getenv"}
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
            ), "engine.py reads the environment"


OTHER_SERVICES = ("registry-service", "registry_service", "weather-service", "weather_service")
SKIPPED_DIRS = {"tests", ".venv", "docs", "__pycache__"}


def service_modules() -> list[Path]:
    return [
        path for path in sorted(ROOT.rglob("*.py"))
        if not SKIPPED_DIRS & set(path.relative_to(ROOT).parts)
    ]


# These two lines are the fixed service names used as the 503 detail and in log lines, as the spec
# requires. They are allowed by file and exact line text. Any other mention, even in a comment or a
# docstring, fails.
ALLOWED_LINES = {
    "planner.py": {'REGISTRY = "registry-service"', 'WEATHER = "weather-service"'},
}


def test_no_imports_from_other_services():
    modules = service_modules()
    assert {path.name for path in modules} >= {"engine.py", "upstream.py", "main.py", "planner.py"}
    for path in modules:
        allowed = ALLOWED_LINES.get(path.name, set())
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if line.strip() in allowed:
                continue
            for name in OTHER_SERVICES:
                assert name not in line, f"{path.name}:{number} mentions {name}"
