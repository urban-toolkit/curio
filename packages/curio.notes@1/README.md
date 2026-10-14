# Notes (`curio.notes@1`)

Post-it notes on the canvas. A **Note** node shows its title and its text on a background color of its own. It runs nothing and connects to nothing.

- **Text:** the node's content, in simple markdown: `#` and `##` headings, `- ` bullets, `**bold**`, and `[label](https://…)` links. Nothing else is interpreted, and no HTML is ever rendered.
- **Color:** `appearance.backgroundColor`, a palette name (`yellow`, `pink`, `blue`, `green`, `orange`, `lavender`) or `#rrggbb`. Text is dark or light to suit it.

The **Researcher** agent writes its findings into notes: a yellow note with the question, then a green note per answer, each citing its sources. With this package installed it reuses the Note template and never builds a package of its own.
