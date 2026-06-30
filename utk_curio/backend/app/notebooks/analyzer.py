"""
Static analysis of Jupyter notebook cells: dependency edges and Altair → Vega-Lite
spec extraction.
"""
import ast
import builtins
import re

_PYTHON_BUILTINS = set(dir(builtins))

# ── AST helpers ───────────────────────────────────────────────────────────────

def _collect_assign_target(node, out):
    if isinstance(node, ast.Name):
        out.add(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            _collect_assign_target(elt, out)
    elif isinstance(node, ast.Starred):
        _collect_assign_target(node.value, out)


def _collect_import_names(tree):
    """Names introduced by import statements (library aliases, not data variables)."""
    names = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != '*':
                    names.add(alias.asname or alias.name)
    return names


def _collect_defined(tree):
    """Names assigned at module scope (excludes function/class bodies)."""
    defined = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                _collect_assign_target(t, defined)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            _collect_assign_target(node.target, defined)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                defined.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != '*':
                    defined.add(alias.asname or alias.name)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            _collect_assign_target(node.target, defined)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars:
                    _collect_assign_target(item.optional_vars, defined)
    return defined


def _last_assigned_var(tree):
    """Name of the last module-scope assignment target (Name nodes only)."""
    last = None
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    last = t.id
                elif isinstance(t, (ast.Tuple, ast.List)):
                    for elt in t.elts:
                        if isinstance(elt, ast.Name):
                            last = elt.id
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            t = node.target
            if isinstance(t, ast.Name):
                last = t.id
    return last


class _UsedNamesVisitor(ast.NodeVisitor):
    """Collects Name(Load) references, skipping into function/class bodies."""

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self.used.add(node.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in node.args.defaults + node.args.kw_defaults:
            if default:
                self.visit(default)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        for base in node.bases:
            self.visit(base)
        for decorator in node.decorator_list:
            self.visit(decorator)


# ── Altair → Vega-Lite spec extraction ───────────────────────────────────────

_ALTAIR_RE = re.compile(r'\balt\.\w+\s*\(')
_ALTAIR_MARK_TYPES = frozenset([
    'line', 'point', 'bar', 'circle', 'square', 'text', 'tick',
    'rule', 'area', 'rect', 'geoshape', 'image', 'trail',
    'boxplot', 'errorband', 'errorbar',
])
_FIELD_RE = re.compile(r'["\']([A-Za-z_][A-Za-z0-9_ ]*)(?::[QONTG])?["\']')


def _extract_altair_fields(code):
    """String literals in the code that look like Vega-Lite field names."""
    fields = set()
    for m in _FIELD_RE.finditer(code):
        name = m.group(1).strip()
        if name and name not in _ALTAIR_MARK_TYPES:
            fields.add(name)
    return fields


def _try_altair_to_spec(code, last_var, external_vars=()):
    """
    Execute Altair code in a mock namespace and return the Vega-Lite spec dict,
    or None if the conversion fails.

    A mock DataFrame built from field names mentioned in the code is used as
    data so Altair can infer column types for shorthand fields.  The 'data' and
    'datasets' keys are stripped from the result so the VIS_VEGA node receives
    real data from its upstream Curio connection at runtime.
    """
    try:
        import altair as alt
        import pandas as pd
        import numpy as np

        fields = _extract_altair_fields(code)
        mock_df = pd.DataFrame({f: [1, 2] for f in fields}) if fields else pd.DataFrame({'_x': [1]})

        ns = {'alt': alt, 'pd': pd, 'np': np, '__builtins__': __builtins__}
        for var in external_vars:
            if var not in ns:
                ns[var] = mock_df.copy()

        exec(compile(code, '<notebook_cell>', 'exec'), ns)
        chart = ns.get(last_var)
        if chart is None or not hasattr(chart, 'to_dict'):
            return None

        spec = chart.to_dict(validate=False)
        spec.pop('data', None)
        spec.pop('datasets', None)
        return spec
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_cells(cells: list[str]) -> dict:
    """
    Analyse a list of notebook cell source strings.

    Returns a dict with:
      - 'analysis': per-cell dicts with 'defined', 'used', 'last_var',
                    and 'altair_spec' (Vega-Lite spec or null).
      - 'edges': list of {source, target} cell-index pairs representing
                 data-flow dependencies.
    """
    analysis = []
    import_names_per_cell = []

    for code in cells:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            analysis.append({'defined': [], 'used': [], 'last_var': None, 'altair_spec': None})
            import_names_per_cell.append(set())
            continue

        defined = _collect_defined(tree)
        import_names = _collect_import_names(tree)

        visitor = _UsedNamesVisitor()
        visitor.used = set()
        visitor.visit(tree)
        used = visitor.used - import_names - _PYTHON_BUILTINS

        last_var = _last_assigned_var(tree)
        altair_spec = (
            _try_altair_to_spec(code, last_var, external_vars=used)
            if last_var and _ALTAIR_RE.search(code)
            else None
        )

        analysis.append({
            'defined': list(defined),
            'used': list(used),
            'last_var': last_var,
            'altair_spec': altair_spec,
        })
        import_names_per_cell.append(import_names)

    # Build dependency edges.
    # Only non-import names are tracked as producers so library aliases (pd, alt, np)
    # don't create spurious edges between an import cell and every cell that uses the library.
    producer: dict[str, int] = {}
    edges: list[dict] = []
    seen: set[tuple] = set()

    for i, cell in enumerate(analysis):
        for name in cell['used']:
            if name in producer:
                key = (producer[name], i)
                if key not in seen:
                    seen.add(key)
                    edges.append({'source': producer[name], 'target': i})
        import_names = import_names_per_cell[i]
        for name in cell['defined']:
            if name not in import_names:
                producer[name] = i

    return {'analysis': analysis, 'edges': edges}

# ── Improved Public API ───────────────────────────────────────────────────────
def runtime_analyze_cells(cells: list[str]) -> dict:
    analysis = []
    import_names_per_cell = []

    # ── Pass 1: Static analysis───────────────────────────────────────────
    for code in cells:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            analysis.append({'defined': [], 'used': [], 'last_var': None, 'altair_spec': None})
            import_names_per_cell.append(set())
            continue

        defined = _collect_defined(tree)
        import_names = _collect_import_names(tree)

        visitor = _UsedNamesVisitor()
        visitor.used = set()
        visitor.visit(tree)
        used = visitor.used - import_names - _PYTHON_BUILTINS

        last_var = _last_assigned_var(tree)
        altair_spec = (
            _try_altair_to_spec(code, last_var, external_vars=used)
            if last_var and _ALTAIR_RE.search(code)
            else None
        )

        analysis.append({
            'defined': list(defined),
            'used': list(used),
            'last_var': last_var,
            'altair_spec': altair_spec,
        })
        import_names_per_cell.append(import_names)

    # ── Pass 2: Runtime analysis──────────────────────────────────────────
    # This might fail if a cell has vega-lite code
    namespace = {'__builtins__': builtins}
    for i, code in enumerate(cells):
        # What keys are in the namespace before code execution
        before = set(namespace.keys())
        try:
            # Try to verify if this is isn't a security risk.
            exec(compile(code, f"<cell_{i}>", "exec"), namespace)
        except Exception:
            analysis[i]['runtime_error'] = True
            continue

        # What keys are in the namespace after code execution
        after = set(namespace.keys())

        # Gather the variables produced in this code execution
        _import_names = import_names_per_cell[i]
        produced = after - before - _import_names - _PYTHON_BUILTINS
        
        types = {}  #{key = var_name: value = var_type}
        for name in produced:
            types[name] = type(namespace[name]).__name__
        
        # The variable types of what was produced
        analysis[i]['runtime_types'] = types

        # Update defined with the variables produced in runtime
        runtime_only = produced - set(analysis[i]['defined'])
        analysis[i]['defined'] = list(runtime_only | set(analysis[i]['defined']))


    # ── Pass 3: Dependency edges──────────────────────────────────────────
    producer: dict[str, int] = {}
    edges: list[dict] = []
    seen: set[tuple] = set()

    for i, cell in enumerate(analysis):
        for name in cell['used']:
            # Added, name not in cell['defined']
            if name in producer and name not in cell['defined']:
                key = (producer[name], i)
                if key not in seen:
                    seen.add(key)
                    edges.append({'source': producer[name], 'target': i})
        import_names = import_names_per_cell[i]
        for name in cell['defined']:
            if name not in import_names:
                producer[name] = i

    return {'analysis': analysis, 'edges': edges}