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
    """Names assigned at module scope (excludes function/class bodies).

    A name only counts as 'defined' if the FIRST time it appears in this
    cell (in source order) is a write. If a name is read before it's
    (re)assigned in the same cell -- including being read on the RHS of
    the very assignment that rebinds it -- it's a dependency on an
    incoming value, not a fresh definition, and is excluded here.
    """
    defined = set()
    loaded = set()  # names already seen as a Load, in source order, this cell only

    def note_loads(node):
        """Record Name-Load references anywhere under node."""
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                loaded.add(child.id)

    def add_targets_if_fresh(target_node):
        names = set()
        _collect_assign_target(target_node, names)
        for name in names:
            if name not in loaded:
                defined.add(name)
            # else: name was read before this store -> dependency, not a fresh define

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            note_loads(node.value)
            for t in node.targets:
                note_loads(t)              # catches e.g. df["x"] = ... (df is Load'd here)
                add_targets_if_fresh(t)
        elif isinstance(node, ast.AugAssign):
            note_loads(node.value)
            note_loads(node.target)        # x += 1 always reads x first
            add_targets_if_fresh(node.target)
        elif isinstance(node, ast.AnnAssign):
            if node.value is not None:
                note_loads(node.value)
            note_loads(node.target)
            add_targets_if_fresh(node.target)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name not in loaded:
                defined.add(node.name)
            note_loads(node)               # free-variable reads inside body still count
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split('.')[0]
                if name not in loaded:
                    defined.add(name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != '*':
                    name = alias.asname or alias.name
                    if name not in loaded:
                        defined.add(name)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            note_loads(node.iter)
            add_targets_if_fresh(node.target)
            for stmt in node.body:
                note_loads(stmt)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                note_loads(item.context_expr)
                if item.optional_vars:
                    add_targets_if_fresh(item.optional_vars)
        else:
            note_loads(node)               # bare expression statements etc.

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


# ── Improved Public API ───────────────────────────────────────────────────────
def analyze_cells(raw_cells: list[str]) -> dict:
    analysis = []
    import_names_per_cell = []

    # ── Cleaning the data of any comments─────────────────────────────────
    
    # Naive regex approach to stripping "FULL LINE" comments
    # Trailing inline comments are left unhandled. The regex
    # required may generate syntactical mistakes in the code.
    cells:list[str] = []
    for code in raw_cells:
        cells.append(re.sub(r'(?m)^\s*#.*\n?', '', code))

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

    # ── Pass 2: Dependency edges──────────────────────────────────────────
    # producer: dict[str, int] = {}
    # edges: list[dict] = []
    # seen: set[tuple] = set()

    # for i, cell in enumerate(analysis):
    #     for name in sorted(cell['used'], key=lambda n: producer.get(n, -1)):
    #         # Added, name not in cell['defined']
    #         if name in producer and name not in cell['defined']:
    #             key = (producer[name], i)
    #             if key not in seen:
    #                 seen.add(key)
    #                 # Added, the variable 'parent_var'. 'parent_var' is the variable that connects two cells
    #                 edges.append({'source': producer[name], 'target': i, 'parent_var': name})
    #     import_names = import_names_per_cell[i]
    #     for name in cell['defined']:
    #         if name not in import_names:
    #             producer[name] = i

    # return {'analysis': analysis, 'edges': edges}

    producer: dict[str, int] = {}
    edges: list[dict] = []
    edge_index: dict[tuple, int] = {}  # (source, target) -> index into edges list

    for i, cell in enumerate(analysis):
        for name in sorted(cell['used'], key=lambda n: producer.get(n, -1)):
            if name in producer and name not in cell['defined']:
                key = (producer[name], i)
                if key not in edge_index:
                    edge_index[key] = len(edges)
                    edges.append({'source': producer[name], 'target': i, 'parent_var': name})
                else:
                    edges[edge_index[key]]['parent_var'] += f", {name}"
        import_names = import_names_per_cell[i]
        for name in cell['defined']:
            if name not in import_names:
                producer[name] = i

    return {'analysis': analysis, 'edges': edges}