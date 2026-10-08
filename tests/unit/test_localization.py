# -*- coding: utf-8 -*-
"""Guard-тест этапа 7.8: кириллица в views/forms.py только через t(); покрытие ключей.

Исключения (конвенция проекта, см. этап 6.6): docstrings и verbose_name/help_text.
Юниты-суффиксы в шаблонах (км, л, л.с.) — принятая типографика, не текст интерфейса.
"""

import ast
import pathlib
import re

CYR = re.compile(r"[А-Яа-яЁё]")
ALLOWED_KW = {"verbose_name", "help_text"}
APPS_DIR = pathlib.Path("apps")
TEMPLATES_DIR = pathlib.Path("templates")


class _Collector(ast.NodeVisitor):
    def __init__(self):
        self.docstrings = set()
        self.allowed = set()
        self.hits = []

    def _mark_doc(self, node):
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            self.docstrings.add(id(body[0].value))

    def visit_Module(self, node):
        self._mark_doc(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self._mark_doc(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self._mark_doc(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_keyword(self, node):
        if node.arg in ALLOWED_KW and isinstance(node.value, ast.Constant):
            self.allowed.add(id(node.value))
        self.generic_visit(node)

    def visit_Assign(self, node):
        for t in node.targets:
            name = getattr(t, "id", None) or getattr(t, "attr", None)
            if name in ALLOWED_KW and isinstance(node.value, ast.Constant):
                self.allowed.add(id(node.value))
        self.generic_visit(node)

    def visit_Constant(self, node):
        if (
            isinstance(node.value, str)
            and CYR.search(node.value)
            and id(node) not in self.docstrings
            and id(node) not in self.allowed
        ):
            self.hits.append(node)


def _violations():
    out = []
    for path in sorted(APPS_DIR.rglob("*.py")):
        if "migrations" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name not in ("views.py", "forms.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        collector = _Collector()
        collector.visit(tree)
        for node in collector.hits:
            out.append(f"{path}:{node.lineno}: {node.value[:60]!r}")
    return out


def test_no_cyrillic_literals_in_views_forms():
    assert not _violations()


def test_lang_file_has_no_duplicate_keys():
    keys = []
    for line in pathlib.Path("locale/ru_ru.lang").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.append(line.split("=", 1)[0].strip())
    dups = {k for k in keys if keys.count(k) > 1}
    assert not dups, f"дубликаты ключей: {sorted(dups)}"


def _lang_keys():
    out = set()
    for line in pathlib.Path("locale/ru_ru.lang").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            out.add(line.split("=", 1)[0].strip())
    return out


# Ревью №10: t() печатает сырой ключ при пропуске в lang — покрываем статические
# литеральные вызовы (t("...")/t('...')/`{% t %}`); динамические f-ключи не ловятся.
PY_T = re.compile(r"""(?<![A-Za-z_])t\(\s*(["'])((?:(?!\1)[^\\]|\\.)*?)\1\s*\)""")
TPL_T = re.compile(r"\{%(?:[-\s])?t\s+['\"]([^'\"]+)['\"]")


def test_all_literal_t_keys_exist_in_lang():
    lang = _lang_keys()
    missing = set()
    for path in pathlib.Path("apps").rglob("*.py"):
        if "migrations" in path.parts or "__pycache__" in path.parts:
            continue
        src = path.read_text(encoding="utf-8")
        for _q, key in PY_T.findall(src):
            if "." in key and not key.startswith(("http", "django")) and key not in lang:
                missing.add(f"{path}: {key}")
    for path in pathlib.Path("templates").rglob("*.html"):
        src = path.read_text(encoding="utf-8")
        for key in TPL_T.findall(src):
            if "." in key and key not in lang:
                missing.add(f"{path}: {key}")
    assert not missing, "ключи вне ru_ru.lang:\n" + "\n".join(sorted(missing))
