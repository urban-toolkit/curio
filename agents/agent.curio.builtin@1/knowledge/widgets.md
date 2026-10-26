## Widgets

A widget is a value a node's code reads that the user sets in the node's Widgets tab without editing the code: a threshold, a factor, a season, a list of years. A node declares its widgets in "metadata"."widgets", shaped as the Trill schema above shows. Each has a "name" (letters, digits and underscores), a "type" ({{widgets.kinds}}), a "label", a "default", and "options" where its type takes them: "choices" for a choice, a checkbox group or a multi-select, and "min", "max", "step" and "units" for a number or a slider, which needs "min" and "max".

The node's code or spec places each widget where its value is used, as its reference: `{{widgets.reference:threshold}}` for the widget named threshold. A run replaces the reference with the widget's value ("value" once the user set one, else "default"). On its own a reference becomes a value of the code's language: a number, a quoted text, a list, true or false. Inside a quoted text it becomes the value's text. Never type a widget's value into the code in its place, and never place a reference to a widget the node does not declare.

A value several nodes read is a widget on one {{template.label:curio.builtin/computation-analysis}} node that returns it, wired into each reader.

A node already on the canvas takes new widget values through node.settings.write: its "widgets" maps each widget's name to the new value, which must fit the widget's type and options as a value typed in the Widgets tab must. The node's code stays as it was.
