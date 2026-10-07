import React from "react";

import { discoveryCatalogApi, type DiscoveryPlace } from "../../services/discoveryCatalog";
import styles from "./DiscoveryAddDialog.module.css";

/**
 * Searching a place by name: the field, the search, and the attribution
 * OpenStreetMap's licence asks for. Shared by the Discovery area field and the
 * location widget (#662).
 *
 * A place is looked up only when asked for (Search, Enter, or a download that
 * needs it), never as it is typed: Nominatim's usage policy forbids
 * auto-complete on its API.
 */

/** A search field that searches on Enter or on its button, and not before. */
export function SearchBox({
  value,
  onChange,
  onSearch,
  placeholder,
  label,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  onSearch: () => void;
  placeholder: string;
  label: string;
  disabled?: boolean;
}) {
  const ready = !disabled && value.trim() !== "";
  return (
    <div className={styles.range}>
      <input
        className={styles.input}
        type="search"
        placeholder={placeholder}
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key !== "Enter") return;
          // The field sits inside the dialog: Enter searches, it does not submit.
          e.preventDefault();
          if (ready) onSearch();
        }}
      />
      <button type="button" className={styles.modeBtn} disabled={!ready} onClick={onSearch}>
        Search
      </button>
    </div>
  );
}

/** Where the places come from, as OpenStreetMap's licence asks. */
export function PlaceAttribution() {
  return (
    <p className={styles.hint}>
      Places from Nominatim, data ©{" "}
      <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer noopener">
        OpenStreetMap contributors ↗
      </a>
    </p>
  );
}

export interface PlaceSearch {
  places: DiscoveryPlace[];
  error: string | null;
  loading: boolean;
  /** A search has run, so an empty list means none was found. */
  searched: boolean;
  search: (query: string) => void;
}

/**
 * The place a named area's **Within** stands for: the first OpenStreetMap
 * boundary the place search finds for *text*. Its `name` is OpenStreetMap's
 * own, in the local language (Köln for Cologne), which is the name the loader
 * matches. Null when the search finds no boundary.
 */
export async function findBoundary(text: string, signal?: AbortSignal): Promise<DiscoveryPlace | null> {
  const { places } = await discoveryCatalogApi.searchPlaces(text.trim(), signal);
  return places.find((place) => place.boundary) ?? null;
}

/** What is said when **Within** finds no boundary. */
export function noBoundaryCalled(text: string): string {
  return `No city or region called "${text.trim()}" in OpenStreetMap.`;
}

export interface BoundaryLookup {
  /** The last text looked up and the boundary found for it, null for none. */
  result: { text: string; place: DiscoveryPlace | null; error: string | null } | null;
  looking: boolean;
  /** Look *text* up, unless it is the text last found; resolves to its boundary or null. */
  lookUp: (text: string) => Promise<DiscoveryPlace | null>;
}

/** `findBoundary` for a field: one lookup per ask, a new ask aborting the one still running. */
export function useBoundaryLookup(): BoundaryLookup {
  const [result, setResult] = React.useState<BoundaryLookup["result"]>(null);
  const [looking, setLooking] = React.useState(false);
  const last = React.useRef<BoundaryLookup["result"]>(null);
  const running = React.useRef<AbortController | null>(null);
  React.useEffect(() => () => running.current?.abort(), []);
  const lookUp = React.useCallback(async (raw: string) => {
    const text = raw.trim();
    if (!text) return null;
    if (last.current?.text === text && !last.current.error) return last.current.place;
    running.current?.abort();
    const controller = new AbortController();
    running.current = controller;
    setLooking(true);
    let next: NonNullable<BoundaryLookup["result"]>;
    try {
      next = { text, place: await findBoundary(text, controller.signal), error: null };
    } catch (e) {
      next = { text, place: null, error: (e as Error).message || "The place search did not answer." };
    }
    if (controller.signal.aborted) return null;
    last.current = next;
    setResult(next);
    setLooking(false);
    return next.place;
  }, []);
  return { result, looking, lookUp };
}

/** One place search per ask; a new ask aborts the one still running. */
export function usePlaceSearch(): PlaceSearch {
  const [state, setState] = React.useState({
    places: [] as DiscoveryPlace[],
    error: null as string | null,
    loading: false,
    searched: false,
  });
  const running = React.useRef<AbortController | null>(null);
  React.useEffect(() => () => running.current?.abort(), []);
  const search = React.useCallback((query: string) => {
    const q = query.trim();
    if (!q) return;
    running.current?.abort();
    const controller = new AbortController();
    running.current = controller;
    setState((s) => ({ ...s, loading: true, error: null }));
    discoveryCatalogApi
      .searchPlaces(q, controller.signal)
      .then((res) => setState({ places: res.places, error: null, loading: false, searched: true }))
      .catch((e: Error) => {
        if (controller.signal.aborted) return;
        setState({
          places: [],
          error: e.message || "The place search did not answer.",
          loading: false,
          searched: true,
        });
      });
  }, []);
  return { ...state, search };
}
