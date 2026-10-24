/**
 * The Map Edits node's layer workbench (#662): the layers the node is fed,
 * and what can be done with each layer, one step at a time.
 *
 * 1. The layers (`LayerList`), as cards grouped by the geometry their
 *    features have. + New data layer makes one (`NewLayerForm`): a name, its
 *    geometry and the properties its features carry.
 * 2. A layer picked: what to do with it (`LayerActions`): Add, Edit, Remove
 *    or Add a property.
 * 3. The action: its form here (`AddForm`; `EditFeatureForm`, with its
 *    `GeometryTools`, `EditManyForm` and `EditRuleForm`; `RemoveForm`;
 *    `AddPropertyForm`), its drawing on the map.
 *
 * The workbench holds what every form reads and writes, so a rule, a value
 * being typed or a pick outlives the form it was made in.
 *
 * The node feeds the Autark maps it is linked to (*surfaces*), and the
 * drawing happens on them (`MapEditOverlay`, through `mapEditBus`). A pick
 * there is the map's selection, which the interaction edge brings the node
 * (*incoming*), and what the node picks, or a rule matches, goes back the
 * same way (*onSelection*). Every action becomes an entry of the node's edit
 * log, through *onEdit*.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import type { SelectionId } from "../../utils/references/selectionTags";
import {
  NEW_LAYER_KEY,
  type EditValue,
  type FeatureEdit,
  type Geometry,
  type NewLayerDef,
  type PropertyDef,
} from "../../utils/editFeatures/editFeatures";
import {
  GEOMETRY_KIND,
  KIND_NOUN,
  editedFeatures,
  formDefaults,
  formValues,
  isGeographic,
  mainKind,
  nextId,
  propertiesFor,
  withAddedColumns,
  type EditedFeature,
  type GeometryKind,
} from "../../utils/editFeatures/layerModel";
import { evaluate, exprProblem, parseExpr, truthy } from "../../utils/editFeatures/editExpr";
import { areaProblem, drawnRefusal, layerFormat, reshapeRefusal, type ReshapeGesture } from "../../utils/editFeatures/areaCheck";
import { partRedraw, partsRefusal, rowsOf, samePart } from "../../utils/editFeatures/featureParts";
import { publishMapSession, type MapEditMode, type ReshapedPart } from "../../utils/editFeatures/mapEditBus";
import { editSelection, sameIds, selectedIdsIn } from "../../utils/editFeatures/mapEditSelection";
import { mapTableName } from "../../utils/editFeatures/mapEditsPreview";
import { withPart } from "../../utils/editFeatures/geometryParts";
import { NodeType } from "../../constants";
import LayerList from "./LayerList";
import NewLayerForm from "./NewLayerForm";
import LayerActions from "./LayerActions";
import AddForm from "./AddForm";
import EditFeatureForm from "./EditFeatureForm";
import GeometryTools, { type ShapeMode } from "./GeometryTools";
import EditManyForm from "./EditManyForm";
import EditRuleForm from "./EditRuleForm";
import RemoveForm from "./RemoveForm";
import AddPropertyForm, { type NewProperty } from "./AddPropertyForm";
import { ruleText, type Condition, type RuleProps } from "./RuleBuilder";
import type { RuleOp, ValueChangeState } from "./ValueChange";
import { BackRow, PickBy, SoloSwitch, type PickMode } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

/** An Autark map the node feeds and is linked to: where it picks and draws. */
export interface EditSurface {
  mapId: string;
  /** The circle the node feeds there, among the map's wired circles. */
  position: number;
  /** Whether the map has more than one wired circle. */
  several: boolean;
}


/** A layer the workbench offers: one of the input's, or one the node makes. */
export interface WorkbenchLayer {
  /** Its name in the edit log: the input's layer name, or the new layer's. */
  name: string;
  /** Shown in the list. */
  label: string;
  /** The table the map draws it as (`input_0`), when it is one of the input's. */
  table?: string;
  /** Whether the input names the layer itself, rather than by its place. */
  ownName?: boolean;
  fc: { features?: any[]; crs?: any };
  /** The column that identifies its features, or undefined when it has none. */
  key?: string;
  /** Set for a layer the node makes. */
  newLayer?: NewLayerDef;
}

export type Action = "add" | "edit" | "remove" | "property";

export default function LayerWorkbench({
  layers,
  edits,
  nodeLayer,
  writable,
  picked,
  setPicked,
  onEdit,
  onEdits,
  onNewLayer,
  removePickedRef,
  surfaces,
  circles = 1,
  incoming,
  onSelection,
  nodeId = "",
}: {
  layers: WorkbenchLayer[];
  edits: readonly FeatureEdit[];
  /** The layer the log's edits apply to when they name none. */
  nodeLayer: string | null;
  writable: boolean;
  /** The features picked in the layer being worked on. */
  picked: SelectionId[];
  setPicked: (ids: SelectionId[]) => void;
  /**
   * One entry for the log, on *layer*; with *property*, the property a new
   * layer's next features are asked for, written in the same change.
   */
  onEdit: (edit: FeatureEdit, layer: WorkbenchLayer, property?: PropertyDef) => void;
  /** Several entries at once, on *layer*. */
  onEdits: (edits: FeatureEdit[], layer: WorkbenchLayer) => void;
  onNewLayer: (def: NewLayerDef) => void;
  /** Set to what removes the picked features of the layer worked on (the body's Delete): true when it did. */
  removePickedRef?: React.MutableRefObject<(() => boolean) | null>;
  /** The Autark maps the node feeds and is linked to: the picking and drawing happen there. */
  surfaces: EditSurface[];
  /** How many circles feed the node: its code names every layer when more than one. */
  circles?: number;
  /** The selections the interaction edges bring the node (its `data.interactions`): a pick on a map is one. */
  incoming?: unknown;
  /** Sends what the node selects, which the maps light up; null when it selects nothing. */
  onSelection?: (details: Record<string, any> | null) => void;
  nodeId?: string;
}) {
  const [activeName, setActiveName] = useState<string | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [creating, setCreating] = useState(false);
  const [drawn, setDrawn] = useState<Geometry | null>(null);
  const [texts, setTexts] = useState<Record<string, string>>({});
  // How the picked feature's shape is changed, or null: neither, and a drag pans the map.
  const [shapeMode, setShapeMode] = useState<ShapeMode>(null);
  const [editTexts, setEditTexts] = useState<Record<string, string>>({});
  const [newProp, setNewProp] = useState<NewProperty>({ name: "", type: "text", value: "" });
  const [removeBy, setRemoveBy] = useState<PickMode>("click");
  // Editing by a rule: what it does to the features it matches, in which column, by what.
  const [editBy, setEditBy] = useState<PickMode>("click");
  const [ruleOp, setRuleOp] = useState<RuleOp>("set");
  const [ruleColumn, setRuleColumn] = useState("");
  const [ruleValue, setRuleValue] = useState("");
  // Show only this layer: the map hides its other layers while one is worked on.
  const [solo, setSolo] = useState(false);
  const [conditions, setConditions] = useState<Condition[]>([{ column: "", test: "is", value: "" }]);

  // What was just added or edited, lit up on the map once it draws them again.
  const [recent, setRecent] = useState<SelectionId[]>([]);
  // Drawing one more part: of the feature being added ("draft") or of the picked one.
  const [partFor, setPartFor] = useState<"draft" | "picked" | null>(null);

  const active = layers.find((l) => l.name === activeName) ?? null;
  useEffect(() => {
    setDrawn(null);
    setPicked([]);
    setRecent([]);
    setPartFor(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeName, action]);
  // A pick names features of the layer worked on, by its id column, on the
  // maps linked: it starts anew when the layer, its id column or those maps
  // change, and ends with the workbench (the node unlinked, its code
  // unreadable, or its layers read again). An edit that writes into the
  // node's code the layer and the id column the pick was made by changes
  // neither, and keeps it.
  const mapIds = surfaces.map((surface) => surface.mapId).join(" ");
  useEffect(() => {
    setPicked([]);
    return () => setPicked([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.name, active?.key, mapIds]);

  const kind: GeometryKind | null = active ? (active.newLayer ? GEOMETRY_KIND[active.newLayer.geometry] : mainKind(active.fc)) : null;
  // A feature is called by its geometry ("point", "line", "area"), never by a
  // guess from the layer's name.
  const nouns = kind ? { one: KIND_NOUN[kind], many: `${KIND_NOUN[kind]}s` } : { one: "feature", many: "features" };
  const defs = useMemo(
    () => (active ? withAddedColumns(propertiesFor(active.fc, active.key, active.newLayer), edits, active.name, nodeLayer) : []),
    [active, edits, nodeLayer],
  );
  const features = useMemo(
    () => (active ? editedFeatures(active.fc, edits, active.key ?? (active.newLayer ? "id" : undefined), active.name, nodeLayer) : []),
    [active, edits, nodeLayer],
  );
  // A fresh rule for each layer. Keyed on the layer, not on defs: defs is
  // rebuilt after every edit, which cleared a rule just applied.
  useEffect(() => {
    setConditions([{ column: defs[0]?.name ?? "", test: "is", value: "" }]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.name]);
  const geographic = active ? isGeographic(active.fc) || (active.newLayer ? isGeographic(layers.find((l) => !l.newLayer)?.fc) : false) : false;
  /** The column the layer worked on names its features by. */
  const layerKey = active ? active.key ?? (active.newLayer ? NEW_LAYER_KEY : undefined) : undefined;
  const pickedOne = picked.length === 1 ? features.find((f) => f.id !== null && String(f.id) === String(picked[0])) : undefined;
  // The picked feature's rows, its parts: an OSM building of several parts
  // is a row for each. The map's tools change one at a time, each named by its
  // own osm_id; a feature whose rows nothing tells apart keeps its shape.
  const pickedRows = useMemo(() => (pickedOne ? rowsOf(features, pickedOne.id) : []), [features, pickedOne]);
  const shapeRefusal = partsRefusal(pickedRows, layerKey);
  const textsOf = (f: EditedFeature) =>
    Object.fromEntries(defs.map((d) => [d.name, f.properties[d.name] === null || f.properties[d.name] === undefined ? "" : String(f.properties[d.name])]));
  useEffect(() => {
    setEditTexts(pickedOne ? textsOf(pickedOne) : {});
    setPartFor((current) => (current === "picked" ? null : current));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickedOne?.id, defs]);

  // What a rule picks now, among the features as the log leaves them.
  const byRule = (action === "remove" && removeBy === "rule") || (action === "edit" && editBy === "rule");
  const rule = byRule ? ruleText(conditions, defs) : null;
  const ruleProblem = rule ? exprProblem(rule) : null;
  const matches = useMemo<SelectionId[] | null>(() => {
    if (!rule || ruleProblem) return null;
    const condition = parseExpr(rule);
    return features.filter((f) => f.id !== null && truthy(evaluate(condition, f.properties as any))).map((f) => f.id as SelectionId);
  }, [rule, ruleProblem, features]);

  // Why autk-db would refuse an area of the layer worked on, as the map hands
  // it over: with it, the whole layer, which the map then draws none of.
  const problemOf = (geometry: Geometry) => (active ? areaProblem(geometry, layerFormat(active.fc, geometry)) : null);
  // A problem a gesture makes: one the shape *after* has and the shape
  // *before* it did not. A shape its layer already holds with one, which a
  // layer autk-db does not check can, still takes every gesture.
  const madeProblem = (before: Geometry | null | undefined, after: Geometry) => {
    const problem = problemOf(after);
    return problem && !(before && problemOf(before)) ? problem : null;
  };
  // A part drawn is added to the feature being added, or to the picked one:
  // to the part the click that picked it landed on, else its first; its
  // other parts keep their shapes. An area drawn that autk-db would refuse,
  // or a part that makes one, is not added: the words the map's tip says why
  // come back.
  const onDrawn = (geometry: Geometry, pickedRow?: EditedFeature | null): string | null => {
    if (partFor === "draft" && drawn) {
      const merged = withPart(drawn, geometry) ?? drawn;
      const problem = madeProblem(drawn, merged);
      if (problem) return drawnRefusal(problem, "part");
      setDrawn(merged);
      setPartFor(null);
      return null;
    }
    if (partFor === "picked" && active && pickedRows.length > 0) {
      const row = pickedRows.find((r) => samePart(r, pickedRow)) ?? pickedRows[0];
      const merged = row.geometry ? withPart(row.geometry, geometry) : null;
      const problem = merged ? madeProblem(row.geometry, merged) : null;
      if (problem) return drawnRefusal(problem, "part");
      const edit = merged ? partRedraw(features, row, layerKey, merged) : null;
      if (edit && row.id !== null) {
        onEdit(edit, active);
        setRecent([row.id]);
      }
      setPartFor(null);
      return null;
    }
    const problem = problemOf(geometry);
    if (problem) return drawnRefusal(problem, "area");
    setDrawn(geometry);
    return null;
  };
  // New shapes for parts of the picked feature, made in one gesture (*how*):
  // one change, an edit for each part, each named alone. None is written when
  // the gesture makes one autk-db would refuse: the words the map's tip says
  // why come back.
  const onReshape = (parts: ReshapedPart[], how?: ReshapeGesture): string | null => {
    if (!active || parts.length === 0) return null;
    for (const { row, geometry } of parts) {
      const problem = madeProblem(row.geometry, geometry);
      if (problem) return reshapeRefusal(problem, how);
    }
    const edits = parts.flatMap(({ row, geometry }) => {
      const edit = partRedraw(features, row, layerKey, geometry);
      return edit ? [edit] : [];
    });
    if (edits.length !== parts.length) return null;
    if (edits.length === 1) onEdit(edits[0], active);
    else onEdits(edits, active);
    if (parts[0].row.id !== null) setRecent([parts[0].row.id]);
    return null;
  };

  // What a click on the map does now: nothing until an action that draws.
  const mode: MapEditMode | null =
    !active || !action || action === "property"
      ? null
      : action === "add"
        ? drawn && partFor !== "draft" ? "select" : "draw"
        : action === "edit" && editBy === "rule"
          ? "select" // a rule changes values only: no points or features to move
          // A feature whose parts nothing tells apart keeps its shape.
          : action === "edit" && pickedOne && shapeRefusal === null && partFor === "picked"
          ? "draw"
          : action === "edit" && pickedOne && shapeRefusal === null && shapeMode
            ? shapeMode
            : "select";
  /** The table *surface*'s map draws *layer* under. */
  const tableOn = (surface: EditSurface, layer: WorkbenchLayer) =>
    mapTableName(layer.table ?? layer.name, !!layer.newLayer || !!layer.ownName, { ...surface, circles });

  // A pick on a map: the map's selection, which the interaction edge carries
  // here, replaces the pick, read on the layer worked on by its id column; a
  // selection of another layer picks nothing here. A pick of nothing, a click
  // on no feature or the map drawn again by a run, also stops lighting up
  // what was just edited. Not while a shape waits to be added, nor while a
  // rule picks.
  useEffect(() => {
    if (!active || !layerKey || !mode || drawn || byRule) return;
    const ids = selectedIdsIn(
      incoming,
      (from, layer) => surfaces.some((surface) => surface.mapId === from && (layer ?? tableOn(surface, active)) === tableOn(surface, active)),
      features,
    );
    if (ids === null) return;
    if (!sameIds(ids, picked)) setPicked(ids);
    if (ids.length === 0) setRecent([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incoming]);

  // What the node selects, which the maps light up: what a rule matches while
  // a rule picks, else the pick, else what was just added or edited.
  const outgoing = byRule ? matches ?? [] : picked.length > 0 ? picked : recent;
  const outgoingKey = JSON.stringify(outgoing);
  useEffect(() => {
    if (!onSelection) return;
    if (!active || !layerKey || surfaces.length === 0) onSelection(null);
    else onSelection(editSelection(outgoing, layerKey, tableOn(surfaces[0], active), NodeType.EDIT_FEATURES));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outgoingKey, active?.name, layerKey, JSON.stringify(surfaces)]);

  // Linked to a map: the action is drawn there.
  const handlers = useRef({ onDrawn, onReshape });
  handlers.current = { onDrawn, onReshape };
  // The body's Delete: the features picked to remove or edit, removed as Remove removes them.
  if (removePickedRef) {
    removePickedRef.current = () => {
      if (!writable || !active || !(active.key || active.newLayer) || picked.length === 0 || drawn) return false;
      if (action !== "remove" && action !== "edit") return false;
      onEdit({ op: "remove", ids: picked }, active);
      setPicked([]);
      return true;
    };
  }
  // The drawing tools, lent to each map the node feeds and is linked to: the
  // layer worked on as that map names it, the mode of the action and the
  // shape being drawn.
  const surfacesKey = JSON.stringify(surfaces);
  useEffect(() => {
    for (const surface of surfaces) {
      if (!active || !kind || (!mode && !solo)) {
        publishMapSession(surface.mapId, nodeId, null);
        continue;
      }
      const table = tableOn(surface, active);
      publishMapSession(surface.mapId, nodeId, {
        interactionId: nodeId,
        solo: solo ? table : null,
        active: !mode ? null : {
          table,
          label: active.label,
          kind,
          noun: nouns.one,
          mode,
          rule: byRule,
          features,
          draft: drawn,
          geographic,
          key: layerKey,
        },
        onDrawn: (geometry, pickedRow) => handlers.current.onDrawn(geometry, pickedRow),
        onReshape: (parts, how) => handlers.current.onReshape(parts, how),
        onShapeDone: () => setShapeMode(null),
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [surfacesKey, active, kind, mode, features, drawn, geographic, nouns.one, solo, byRule, layerKey]);
  // Back on the list of layers, the map shows them all again.
  useEffect(() => {
    if (activeName === null) setSolo(false);
  }, [activeName]);
  // A map no longer linked, and every map when the node leaves: the node's
  // session taken back from it, and only the node's.
  useEffect(() => {
    const mapIds = surfaces.map((surface) => surface.mapId);
    return () => {
      for (const mapId of mapIds) publishMapSession(mapId, nodeId, null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [surfacesKey, nodeId]);

  const addDrawn = () => {
    if (!active || !drawn) return;
    const key = active.key ?? "id";
    const id = nextId(active.fc, edits, key, active.newLayer ? active.name : active.name === nodeLayer ? undefined : active.name);
    onEdit({ op: "add", id, geometry: drawn, values: formValues(defs, texts) }, active);
    setRecent([id as SelectionId]);
    setDrawn(null);
    setTexts(formDefaults(defs));
  };
  const dirty = pickedOne ? defs.filter((def) => String(pickedOne.properties[def.name] ?? "") !== String(formValues([def], editTexts)[def.name] ?? "")) : [];
  const applyValues = () => {
    if (!active || !pickedOne || pickedOne.id === null) return;
    const values = formValues(defs, editTexts);
    const changed: FeatureEdit[] = dirty.map((def) => ({ op: "set", ids: [pickedOne.id as SelectionId], column: def.name, value: (values[def.name] ?? null) as EditValue }));
    if (changed.length > 0) {
      onEdits(changed, active);
      setRecent([pickedOne.id as SelectionId]);
    }
  };
  const go = (next: Action) => {
    setAction(next);
    if (next === "add") setTexts(formDefaults(defs));
  };

  if (creating) {
    return (
      <div className={styles.workbench} data-testid="interaction-workbench">
        <NewLayerForm
          taken={layers.map((l) => l.name)}
          onCancel={() => setCreating(false)}
          onCreate={(def) => {
            onNewLayer(def);
            setCreating(false);
            setActiveName(def.name);
            setAction("add");
            setTexts(formDefaults(def.properties ?? []));
          }}
        />
      </div>
    );
  }

  if (!active || !kind) {
    return (
      <div className={styles.workbench} data-testid="interaction-workbench">
        <LayerList
          layers={layers}
          edits={edits}
          nodeLayer={nodeLayer}
          writable={writable}
          onOpen={(name) => {
            setActiveName(name);
            setAction(null);
          }}
          onNewLayer={() => setCreating(true)}
        />
      </div>
    );
  }

  const canEdit = !!(active.key || active.newLayer);
  const soloSwitch = <SoloSwitch solo={solo} setSolo={setSolo} />;

  if (!action) {
    return (
      <div className={styles.workbench} data-testid="interaction-workbench">
        <div className={styles.form} data-testid="interaction-active-layer" data-layer={active.name} data-kind={kind}>
          <LayerActions
            active={active}
            kind={kind}
            nouns={nouns}
            count={features.length}
            canEdit={canEdit}
            writable={writable}
            solo={soloSwitch}
            onAllLayers={() => setActiveName(null)}
            onAction={go}
            onNewLayer={() => setCreating(true)}
          />
        </div>
      </div>
    );
  }

  const back = <BackRow label={active.label} onBack={() => setAction(null)} solo={soloSwitch} />;
  const ruleProps: RuleProps = { conditions, setConditions, defs, problem: ruleProblem, matches, total: features.length, nouns };
  const change: ValueChangeState = { op: ruleOp, setOp: setRuleOp, column: ruleColumn, setColumn: setRuleColumn, value: ruleValue, setValue: setRuleValue };
  // Edit picks by a click or by a rule; a change of either starts the pick anew.
  const editPickBy = (
    <PickBy
      current={editBy}
      choose={(by) => {
        setEditBy(by);
        setPicked([]);
        setShapeMode(null);
        setPartFor(null);
      }}
      testId="interaction-edit-by-rule"
    />
  );

  let body: React.ReactNode = null;
  if (action === "add") {
    body = (
      <AddForm
        back={back}
        active={active}
        kind={kind}
        nouns={nouns}
        defs={defs}
        drawn={drawn}
        partFor={partFor}
        texts={texts}
        setTexts={setTexts}
        onAdd={addDrawn}
        onAddPart={() => setPartFor("draft")}
        onCancelPart={() => setPartFor(null)}
        onDiscard={() => setDrawn(null)}
      />
    );
  } else if (action === "edit" && editBy === "rule") {
    body = (
      <EditRuleForm
        back={back}
        nouns={nouns}
        pickBy={editPickBy}
        rule={ruleProps}
        where={rule}
        defs={defs}
        change={change}
        onApply={(edit) => {
          onEdit(edit, active);
          setRecent(matches ?? []);
        }}
      />
    );
  } else if (action === "edit" && picked.length > 1) {
    body = (
      <EditManyForm
        back={back}
        nouns={nouns}
        picked={picked}
        defs={defs}
        change={change}
        onApply={(edit) => {
          onEdit(edit, active);
          setRecent(picked);
        }}
        onClearPick={() => setPicked([])}
      />
    );
  } else if (action === "edit") {
    body = (
      <EditFeatureForm
        back={back}
        nouns={nouns}
        pickBy={editPickBy}
        feature={pickedOne}
        geometry={
          pickedOne ? (
            <GeometryTools
              kind={kind}
              nouns={nouns}
              feature={pickedOne}
              refusal={shapeRefusal}
              shapeMode={shapeMode}
              onShapeMode={setShapeMode}
              partFor={partFor}
              onAddPart={() => {
                setShapeMode(null);
                setPartFor("picked");
              }}
              onCancelPart={() => setPartFor(null)}
            />
          ) : null
        }
        defs={defs}
        texts={editTexts}
        setTexts={setEditTexts}
        dirty={dirty}
        nodeId={nodeId}
        onApply={applyValues}
      />
    );
  } else if (action === "remove") {
    body = (
      <RemoveForm
        back={back}
        nouns={nouns}
        removeBy={removeBy}
        setRemoveBy={setRemoveBy}
        picked={picked}
        rule={ruleProps}
        where={rule}
        onRemove={(edit) => {
          onEdit(edit, active);
          setPicked([]);
        }}
      />
    );
  } else if (action === "property") {
    body = (
      <AddPropertyForm
        back={back}
        nouns={nouns}
        active={active}
        defs={defs}
        newProp={newProp}
        setNewProp={setNewProp}
        onAdd={(edit, property) => {
          onEdit(edit, active, property);
          setNewProp({ name: "", type: "text", value: "" });
          setAction(null);
        }}
      />
    );
  }

  return (
    <div className={styles.workbench} data-testid="interaction-workbench">
      <div data-testid="interaction-active-layer" data-layer={active.name} data-kind={kind} className={styles.form}>
        {body}
      </div>
    </div>
  );
}
