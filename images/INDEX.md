# PR images

Drag each file onto its `<!-- IMAGE: … -->` spot in PR.md, in the GitHub editor, then delete the comment and the bold file-name tag. `-before` images are `main` (`3e4386955`) and `-after` images are this branch (`3baeca5b8`). All were captured at 1600×1000 and 2× scale.

| File | Section | Caption |
|---|---|---|
| `01-view-menu-before.png` | Step 0: start | Before (main): View had Save selection as scenario, Duplicate selection and Duplicate as scenario |
| `01-view-menu-after.png` | Step 0: start | The View menu now has **Define scenario** and **Duplicate selection** |
| `02-file-menu-before.png` | Step 0: start | Before (main): File → Save dataflow as scenario |
| `02-file-menu-after.png` | Step 0: start | After: removed from File; Define scenario covers it |
| `03a-before-define-after.png` | Step 1: Scenario-specific nodes | The starting point: *As built* is a scenario, and *Twice as tall*'s nodes (middle and bottom) are not yet |
| `03-define-step1-after.png` | Step 1: Scenario-specific nodes | Step 1: *Heights scaled* was selected when the panel opened, so it is listed. *Rounded heights* is now selected on the canvas |
| `03b-define-step1-added-after.png` | Step 1: Scenario-specific nodes | Step 1: **+ Add selected node** adds it |
| `04-define-step2-after.png` | Step 2: Shared context & outcomes | Step 2, joining the set *As built* is in. *Building heights* and *Compare totals* are **Already in the set**, and *Height factor* is **New to the set**. *Total as built* is not listed, since this scenario does not feed it |
| `06a-define-step3-after.png` | Step 3: Name & set | Step 3: name, color, and the set (this dataflow's set, or a new one) |
| `06-define-step3-duplicate-name-after.png` | Step 3: Name & set | Step 3: "As built" is taken in this set, so the name is flagged and **Save scenario** stays off |
| `06b-define-step3-after.png` | Step 3: Name & set | Step 3: a free name |
| `06c-after-save-after.png` | Step 3: Name & set | Saved: both scenarios in the set *Building heights study*, and the circles show which scenario uses each shared node |
| `07-canvas-expanded-before.png` | On the canvas | Before (main): scenario frames only |
| `07-canvas-expanded-after.png` | On the canvas | After: the set outline and title, gray shared groups, and membership circles |
| `08-canvas-collapsed-before.png` | Collapsed | Before (main): a box that lists the fixed context and outcomes |
| `08-canvas-collapsed-after.png` | Collapsed | After: scenario boxes and shared-group boxes, each a set of cards with status pills |
| `09-in-project-tab-before.png` | The In project tab | Before (main) |
| `09-in-project-tab-after.png` | The In project tab | After: a panel per set, and the card's actions |
| `09b-in-project-hover-before.png` | The In project tab | Before (main): pointing at a card outlined only its fixed context |
| `09b-in-project-hover-after.png` | The In project tab | After: pointing at a card marks its shared context and outcomes on the canvas |
| `09c-set-rename-after.png` | The In project tab | Renaming a set in place |
| `10-edit-scenario-after.png` | Edit scenario | Edit scenario: the panel on a saved scenario |
| `11-duplicate-scenario-after.png` | Duplicate scenario | Duplicate scenario on *Twice as tall*: the copy, *Scenario 1*, lands below in the next color, in the same set, and the panel opens at Name & set. The circles under the shared outcomes show it has none yet |
| `11b-duplicate-canvas-after.png` | Duplicate scenario | After saving the copy |
| `11b-duplicate-canvas-before.png` | Duplicate scenario | Before (main): View → Duplicate as scenario on the same nodes |
| `12-browse-all-before.png` | Browse all, and dragging several scenarios | Before (main): grouped by project |
| `12-browse-all-after.png` | Browse all, and dragging several scenarios | After: grouped by scenario set |
| `13-pick-scenarios-after.png` | Browse all, and dragging several scenarios | Pick scenarios to drag: checkboxes and the Drag 2 scenarios handle |
| `14-after-drop-before.png` | What a drop brings | Before (main): *Real heights* from the shipped `scenarios` example, dropped alone, with its context as a Data Loading node |
| `14b-second-drop-before.png` | What a drop brings | Before (main): a second drop, *Twice as tall*, reused the first drop's context |
| `14a-drop-toast-before.png` | What a drop brings | Before (main): one card dragged; the drop runs the context on the server first |
| `14a-drop-toast-after.png` | What a drop brings | After: *Real heights* and *Twice as tall* checked and dragged by the **Drag 2 scenarios** handle. The context runs on the server first, since the example never ran, and the toast names the new set |
| `14-after-drop-after.png` | What a drop brings | After: they arrive as the set "Building heights (copy)", all collapsed, with the context once and the shared outcomes that came |
| `14c-in-project-after-drop-before.png` | What a drop brings | Before (main): the In project tab after the drops |
| `14c-in-project-after-drop-after.png` | What a drop brings | After: the dropped set in the In project tab |
| `15-details-before.png` | Details and the catalog page | Before (main): Fixed context / Levers / Outcomes |
| `15-details-after.png` | Details and the catalog page | After: Shared context / Scenario-specific nodes / Shared outcomes, and the set |
| `16-catalog-page-before.png` | Details and the catalog page | Before (main): /catalog/scenarios |
| `16-catalog-page-after.png` | Details and the catalog page | After: /catalog/scenarios |
| `17-header-vs-box-before.png` | 7. One node name, `title` (#1248) | Before (main): a dataflow whose nodes have only `title` (as an agent writes them). Headers read "Python Computation" and "Data Loading", while the scenario box reads "Heights scaled" and "Rounded heights" |
| `17-header-vs-box-after.png` | 7. One node name, `title` (#1248) | After: the header and the box show the same name |
| `18-rename-before.png` | 7. One node name, `title` (#1248) | Before (main): built-in nodes cannot be renamed from the header |
| `18-rename-after.png` | 7. One node name, `title` (#1248) | After: "Heights as built" renamed "Heights today" in its header, and the collapsed box shows the new name |
