import React from "react";

import { type DiscoveryAreaValue, type DiscoveryParameter } from "../../services/discoveryCatalog";
import { datasetCatalogApi } from "../../services/datasetCatalog";
import styles from "./DiscoveryAddDialog.module.css";
import { PlaceAttribution, SearchBox, noBoundaryCalled, useBoundaryLookup, usePlaceSearch } from "./placeSearch";

/**
 * An area, with no map: a box from a place search, from four typed
 * coordinates, or from a geo dataset already in your Data Catalog; or, where
 * the source takes them, named OpenStreetMap areas inside a place.
 *
 * The box is always shown back in numbers with its size, checked against the
 * source's limit, so what is sent is what is seen.
 *
 * A place is looked up only when asked for (Search, Enter, or Download for a
 * named area's place), never as it is typed: Nominatim's usage policy forbids
 * auto-complete on its API.
 */

type Box = [number, number, number, number];
type Mode = "place" | "coordinates" | "dataset" | "names";

const MODE_LABEL: Record<Mode, string> = {
  place: "Place",
  coordinates: "Coordinates",
  dataset: "A dataset's extent",
  names: "Named areas",
};

const EARTH_RADIUS_KM = 6371.0088;

/** The area of a WGS84 box on a sphere, in km2: the server's own formula. */
export function boxAreaKm2([west, south, east, north]: Box): number {
  const rad = Math.PI / 180;
  return (
    EARTH_RADIUS_KM ** 2 * (east - west) * rad * Math.abs(Math.sin(north * rad) - Math.sin(south * rad))
  );
}

/** What is wrong with a box, in words, or null when it is one. */
export function boxProblem(box: Box | null, maxAreaKm2?: number): string | null {
  if (!box || box.some((v) => !Number.isFinite(v))) return "Enter four numbers.";
  const [west, south, east, north] = box;
  if (!(west >= -180 && east <= 180 && west < east)) return "West must be left of east, within -180 to 180.";
  if (!(south >= -90 && north <= 90 && south < north)) return "South must be below north, within -90 to 90.";
  if (maxAreaKm2 != null && boxAreaKm2(box) > maxAreaKm2) {
    return `This box covers ${formatKm2(boxAreaKm2(box))}; this source takes at most ${formatKm2(maxAreaKm2)}.`;
  }
  return null;
}

function formatKm2(km2: number): string {
  return `${km2 < 10 ? km2.toFixed(1) : Math.round(km2).toLocaleString()} km²`;
}

function boxText(box: Box): string {
  const [w, s, e, n] = box.map((v) => v.toFixed(4));
  return `${w}, ${s} to ${e}, ${n}`;
}

export interface AreaFieldProps {
  parameter: DiscoveryParameter;
  value: DiscoveryAreaValue | null;
  onChange: (value: DiscoveryAreaValue | null) => void;
}

export function AreaField({ parameter, value, onChange }: AreaFieldProps) {
  const accepts = parameter.accepts ?? ["box"];
  const modes: Mode[] = [
    ...(accepts.includes("box") ? (["place", "coordinates", "dataset"] as Mode[]) : []),
    ...(accepts.includes("names") ? (["names"] as Mode[]) : []),
  ];
  const [mode, setMode] = React.useState<Mode>(modes[0]);
  const box = value && "box" in value ? (value.box as Box) : null;
  const problem = box ? boxProblem(box, parameter.maxAreaKm2) : null;

  return (
    <fieldset className={styles.fieldset} data-parameter={parameter.id}>
      <legend className={styles.fieldLabel}>{parameter.label}</legend>
      {parameter.description ? <p className={styles.hint}>{parameter.description}</p> : null}
      {modes.length > 1 ? (
        <div className={styles.modes} role="tablist" aria-label={`${parameter.label}: how to set it`}>
          {modes.map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              className={mode === m ? `${styles.modeBtn} ${styles.modeBtnActive}` : styles.modeBtn}
              onClick={() => setMode(m)}
            >
              {MODE_LABEL[m]}
            </button>
          ))}
        </div>
      ) : null}

      {mode === "place" ? <PlaceBox label={parameter.label} onPick={(b, label) => onChange({ box: b, label })} /> : null}
      {mode === "coordinates" ? <CoordinateBox box={box} onChange={(b) => onChange(b ? { box: b } : null)} /> : null}
      {mode === "dataset" ? <DatasetBox onPick={(b, label) => onChange({ box: b, label })} /> : null}
      {mode === "names" ? (
        <NamedAreas
          value={value && "names" in value ? value.names : null}
          onChange={(names) => onChange(names ? { names } : null)}
        />
      ) : null}

      {box ? (
        <p className={styles.boxSummary} aria-live="polite">
          {value && "box" in value && value.label ? <strong>{value.label}: </strong> : null}
          {boxText(box)} · {formatKm2(boxAreaKm2(box))}
          {parameter.maxAreaKm2 != null ? ` of at most ${formatKm2(parameter.maxAreaKm2)}` : null}
        </p>
      ) : null}
      {problem ? <p className={styles.warning}>{problem}</p> : null}
    </fieldset>
  );
}

/** Search a place by name and take its box. */
function PlaceBox({ label, onPick }: { label: string; onPick: (box: Box, label: string) => void }) {
  const [text, setText] = React.useState("");
  const { places, error, loading, searched, search } = usePlaceSearch();
  const [picked, setPicked] = React.useState<string | null>(null);
  return (
    <div className={styles.field}>
      <SearchBox
        value={text}
        onChange={setText}
        onSearch={() => search(text)}
        placeholder="A city, a neighbourhood, an address"
        label={`${label}: search a place`}
      />
      {loading ? <p className={styles.hint}>Searching…</p> : null}
      {error ? <p className={styles.warning}>{error}</p> : null}
      {places.length > 0 ? (
        <ul className={styles.places} role="listbox" aria-label="Places found">
          {places.map((place) => (
            <li key={`${place.label}:${place.box.join(",")}`}>
              <button
                type="button"
                role="option"
                aria-selected={picked === place.label}
                className={picked === place.label ? `${styles.place} ${styles.placeActive}` : styles.place}
                onClick={() => {
                  setPicked(place.label);
                  onPick(place.box as Box, place.name);
                }}
              >
                <span>{place.label}</span>
                <span className={styles.hint}>{formatKm2(boxAreaKm2(place.box as Box))}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {searched && !loading && !error && places.length === 0 ? (
        <p className={styles.hint}>No place by that name.</p>
      ) : null}
      <PlaceAttribution />
    </div>
  );
}

/** Four numbers, west, south, east and north. */
function CoordinateBox({ box, onChange }: { box: Box | null; onChange: (box: Box | null) => void }) {
  const [text, setText] = React.useState<string[]>(() => (box ? box.map(String) : ["", "", "", ""]));
  const names = ["West", "South", "East", "North"];
  const update = (index: number, next: string) => {
    const all = text.map((v, i) => (i === index ? next : v));
    setText(all);
    const numbers = all.map((v) => (v.trim() === "" ? Number.NaN : Number(v)));
    onChange(numbers.every(Number.isFinite) ? (numbers as Box) : null);
  };
  return (
    <div className={styles.coordinates}>
      {names.map((name, i) => (
        <label key={name} className={styles.field}>
          <span className={styles.fieldLabel}>{name}</span>
          <input
            className={styles.input}
            inputMode="decimal"
            value={text[i]}
            onChange={(e) => update(i, e.target.value)}
          />
        </label>
      ))}
    </div>
  );
}

/** A geo dataset already in the Data Catalog, and the box it covers. */
function DatasetBox({ onPick }: { onPick: (box: Box, label: string) => void }) {
  const [items, setItems] = React.useState<{ id: string; title: string }[] | null>(null);
  const [chosen, setChosen] = React.useState("");
  const [note, setNote] = React.useState<string | null>(null);
  React.useEffect(() => {
    let live = true;
    datasetCatalogApi
      .listCatalog({})
      .then((res) => {
        if (!live) return;
        const geo = (res.items ?? []).filter(
          (d) => d.featureCount != null || ["geojson", "geotiff", "shp", "collection"].includes(String(d.format)),
        );
        setItems(geo.map((d) => ({ id: d.id, title: d.title || d.id })));
      })
      .catch((e: Error) => live && setNote(e.message || "Could not list your datasets."));
    return () => {
      live = false;
    };
  }, []);
  const pick = async (id: string) => {
    setChosen(id);
    setNote(null);
    if (!id) return;
    try {
      const extent = await datasetCatalogApi.extent(id);
      if (extent.box) onPick(extent.box as Box, extent.title);
      else setNote("That dataset has no location, so it has no extent.");
    } catch (e) {
      setNote((e as Error).message || "Could not read that dataset's extent.");
    }
  };
  if (items == null && !note) return <p className={styles.hint}>Listing your datasets…</p>;
  return (
    <div className={styles.field}>
      <select
        className={styles.input}
        aria-label="A dataset in your Data Catalog"
        value={chosen}
        onChange={(e) => void pick(e.target.value)}
      >
        <option value="">Choose a dataset…</option>
        {(items ?? []).map((item) => (
          <option key={item.id} value={item.id}>
            {item.title}
          </option>
        ))}
      </select>
      {items && items.length === 0 ? <p className={styles.hint}>Your Data Catalog has no dataset with a location.</p> : null}
      {note ? <p className={styles.warning}>{note}</p> : null}
    </div>
  );
}

/**
 * A place to search within, and the named OSM areas inside it.
 *
 * The loader matches both by their OpenStreetMap names, which are in the
 * local language. The place in **Within** is looked up on Enter, or by Search
 * in **Find areas**, and shown as OpenStreetMap names it; **Find areas**
 * searches inside that name. The answer keeps the place as typed, and a
 * download sends it as OpenStreetMap names it (`withOsmPlaceNames`).
 */
function NamedAreas({
  value,
  onChange,
}: {
  value: { geocodeArea: string; areas: string[] } | null;
  onChange: (names: { geocodeArea: string; areas: string[] } | null) => void;
}) {
  const [scope, setScope] = React.useState(value?.geocodeArea ?? "");
  const [areas, setAreas] = React.useState<string[]>(value?.areas ?? []);
  const [text, setText] = React.useState("");
  const { places, error, loading, searched, search } = usePlaceSearch();
  const within = useBoundaryLookup();
  // What Within was found as, while it still says what was looked up.
  const found = within.result && within.result.text === scope.trim() ? within.result : null;
  const boundaries = places.filter((p) => p.boundary);
  const emit = (nextScope: string, nextAreas: string[]) =>
    onChange(nextScope.trim() && nextAreas.length ? { geocodeArea: nextScope.trim(), areas: nextAreas } : null);
  const findAreas = () => {
    void within.lookUp(scope).then((place) => {
      if (place) search(`${text.trim()}, ${place.name}`);
    });
  };
  return (
    <div className={styles.field}>
      <label className={styles.field}>
        <span className={styles.fieldLabel}>Within</span>
        <input
          className={styles.input}
          placeholder="A city or region"
          value={scope}
          onChange={(e) => {
            setScope(e.target.value);
            emit(e.target.value, areas);
          }}
          onKeyDown={(e) => {
            if (e.key !== "Enter") return;
            // The field sits inside the dialog: Enter looks the place up, it does not submit.
            e.preventDefault();
            void within.lookUp(scope);
          }}
        />
      </label>
      {within.looking ? <p className={styles.hint}>Looking up the place…</p> : null}
      {found?.place ? (
        <p className={styles.hint} aria-live="polite">
          <strong>{found.place.name}</strong> · {found.place.label}
        </p>
      ) : null}
      {found && !found.place ? <p className={styles.warning}>{found.error ?? noBoundaryCalled(found.text)}</p> : null}
      <div className={styles.field}>
        <span className={styles.fieldLabel}>Find areas</span>
        <SearchBox
          value={text}
          onChange={setText}
          onSearch={findAreas}
          placeholder="A neighbourhood or district"
          label="Find areas"
          disabled={!scope.trim()}
        />
      </div>
      {loading ? <p className={styles.hint}>Searching…</p> : null}
      {error ? <p className={styles.warning}>{error}</p> : null}
      {searched && !loading && !error && boundaries.length === 0 ? (
        <p className={styles.hint}>No boundary by that name in OpenStreetMap.</p>
      ) : null}
      {boundaries.length > 0 ? (
        <ul className={styles.places} aria-label="Areas found">
          {boundaries.map((place) => (
            <li key={place.label}>
              <button
                type="button"
                className={styles.place}
                disabled={areas.includes(place.name)}
                onClick={() => {
                  const next = [...areas, place.name];
                  setAreas(next);
                  emit(scope, next);
                }}
              >
                <span>{place.name}</span>
                <span className={styles.hint}>{place.label}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {areas.length > 0 ? (
        <div className={styles.chips} aria-label="Areas chosen">
          {areas.map((name) => (
            <span key={name} className={styles.chip}>
              {name}
              <button
                type="button"
                aria-label={`Remove ${name}`}
                onClick={() => {
                  const next = areas.filter((a) => a !== name);
                  setAreas(next);
                  emit(scope, next);
                }}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      ) : null}
      <PlaceAttribution />
    </div>
  );
}

export default AreaField;
