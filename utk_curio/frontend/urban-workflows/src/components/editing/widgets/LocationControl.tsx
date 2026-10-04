import React, { useEffect, useState } from "react";
import styles from "./WidgetTags.module.css";
import { PlaceAttribution, SearchBox, usePlaceSearch } from "../../../pages/discovery/placeSearch";
import type { LocationValue } from "../../../utils/widgets/widgetModel";

/** Coordinates to six decimals, about 10 cm. */
const round6 = (x: number) => Math.round(x * 1e6) / 1e6;

/** The point a place found by the search stands for: the center of its box. */
export function placePoint(box: number[]): LocationValue {
  const [west, south, east, north] = box;
  return { lat: round6((south + north) / 2), lon: round6((west + east) / 2) };
}

const asPoint = (value: unknown): LocationValue | null => {
  const v = value as Partial<LocationValue> | null;
  return v && typeof v === "object" && typeof v.lat === "number" && typeof v.lon === "number"
    ? { lat: v.lat, lon: v.lon }
    : null;
};

/**
 * A location widget's control (#662): a latitude and a longitude, typed, or
 * taken from a place found by name with the Discovery Catalog's place search.
 * Only the coordinates are the value; the place's name is shown, not saved.
 */
export function LocationControl({
  value,
  onCommit,
  label,
  disabled,
}: {
  value: unknown;
  /** Gets every candidate; the widget control checks it. */
  onCommit: (candidate: LocationValue) => void;
  label: string;
  disabled: boolean;
}) {
  const point = asPoint(value);
  const [draft, setDraft] = useState<[string, string]>(() =>
    point ? [String(point.lat), String(point.lon)] : ["", ""],
  );
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const { places, error, loading, searched, search } = usePlaceSearch();

  // A value set from outside replaces the draft, unless the draft already
  // says it ("41." while typing 41.5).
  const valueKey = JSON.stringify(value ?? null);
  useEffect(() => {
    if (!point) return;
    setDraft((d) =>
      d[0].trim() !== "" && d[1].trim() !== "" && Number(d[0]) === point.lat && Number(d[1]) === point.lon
        ? d
        : [String(point.lat), String(point.lon)],
    );
  }, [valueKey]);

  const update = (index: 0 | 1, typed: string) => {
    const next: [string, string] = index === 0 ? [typed, draft[1]] : [draft[0], typed];
    setDraft(next);
    setPicked(null);
    const [lat, lon] = next.map((t) => (t.trim() === "" ? NaN : Number(t)));
    onCommit({ lat, lon });
  };

  return (
    <span className={styles.location}>
      <span className={styles.inline}>
        <input
          type="number"
          step="any"
          min={-90}
          max={90}
          placeholder="Latitude"
          aria-label={`${label} latitude`}
          value={draft[0]}
          disabled={disabled}
          onChange={(e) => update(0, e.target.value)}
        />
        <input
          type="number"
          step="any"
          min={-180}
          max={180}
          placeholder="Longitude"
          aria-label={`${label} longitude`}
          value={draft[1]}
          disabled={disabled}
          onChange={(e) => update(1, e.target.value)}
        />
      </span>
      <SearchBox
        value={text}
        onChange={setText}
        onSearch={() => {
          setPicked(null);
          search(text);
        }}
        placeholder="Or search a place"
        label={`${label}: search a place`}
        disabled={disabled}
      />
      {loading ? <span className={styles.hint}>Searching…</span> : null}
      {error ? <span className={styles.problem}>{error}</span> : null}
      {picked === null && places.length > 0 ? (
        <ul className={styles.places} role="listbox" aria-label="Places found">
          {places.map((place) => (
            <li key={`${place.label}:${place.box.join(",")}`}>
              <button
                type="button"
                role="option"
                aria-selected={false}
                disabled={disabled}
                onClick={() => {
                  setPicked(place.label);
                  onCommit(placePoint(place.box));
                }}
              >
                {place.label}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {searched && !loading && !error && places.length === 0 ? (
        <span className={styles.hint}>No place by that name.</span>
      ) : null}
      {picked !== null ? <span className={styles.hint}>{picked}</span> : null}
      {searched ? <PlaceAttribution /> : null}
    </span>
  );
}

export default LocationControl;
