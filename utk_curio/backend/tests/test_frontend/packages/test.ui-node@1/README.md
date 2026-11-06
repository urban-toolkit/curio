# UI Node

`test.ui-node@1`

A test package, made with `python scripts/new_package.py test.ui-node --with-ui`.
Its one node draws its own interface in place of a code editor. It declares no
Python libraries, so adding it never runs pip. The e2e tests plant it in the
backend's catalog for one test and take it out after.

## Nodes

| Node | Input | Output | What it does |
|---|---|---|---|
| UI Node | DataFrame | DataFrame | Lists the frame's columns; Send this column downstream keeps the chosen column as its output |

## Building

This package ships a compiled behavior bundle. After editing anything under `sources/`:

```bash
cd utk_curio/frontend/urban-workflows
npm run build:packages
```

## License

MIT
