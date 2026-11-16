"""Architecture rules from CLAUDE.md, enforced as tests.

Why a test? A rule that is only written down gets broken by accident. This test parses
every module with `ast` (no code is executed) and fails as soon as a forbidden import
appears, so the layering stays intact as the project grows.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "immo"

# package (relative to src/immo) -> top-level modules it must never import
FORBIDDEN = {
    "core": {"streamlit", "sqlalchemy", "plotly", "requests", "httpx", "urllib3", "aiohttp"},
    "storage": {"streamlit", "plotly"},
    "sources": {"streamlit", "plotly", "sqlalchemy"},
    "pipeline": {"streamlit", "plotly", "sqlalchemy"},
}
# inside the project, core may only import from core
CORE_FORBIDDEN_INTERNAL = ("immo.storage", "immo.sources", "immo.pipeline", "immo.ui")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def test_layers_do_not_import_forbidden_modules():
    problems = []
    for package, forbidden in FORBIDDEN.items():
        for path in (SRC / package).rglob("*.py"):
            for name in _imports(path):
                if name.split(".")[0] in forbidden:
                    problems.append(f"{path.relative_to(SRC)} imports {name}")
    assert not problems, "\n".join(problems)


def test_core_does_not_depend_on_outer_layers():
    problems = []
    for path in (SRC / "core").rglob("*.py"):
        for name in _imports(path):
            if name.startswith(CORE_FORBIDDEN_INTERNAL):
                problems.append(f"{path.relative_to(SRC)} imports {name}")
    assert not problems, "\n".join(problems)


def test_only_the_repository_layer_uses_sqlalchemy():
    problems = []
    for path in SRC.rglob("*.py"):
        if path.parent.name == "storage":
            continue
        if any(name.split(".")[0] == "sqlalchemy" for name in _imports(path)):
            problems.append(str(path.relative_to(SRC)))
    assert not problems, f"SQLAlchemy used outside storage/: {problems}"
