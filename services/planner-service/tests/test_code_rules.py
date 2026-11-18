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
