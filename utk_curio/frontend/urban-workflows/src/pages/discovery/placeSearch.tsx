import React from "react";

import { discoveryCatalogApi, type DiscoveryPlace } from "../../services/discoveryCatalog";
import styles from "./DiscoveryAddDialog.module.css";

/**
 * Searching a place by name: the field, the search, and the attribution
 * OpenStreetMap's licence asks for. Shared by the Discovery area field and the
 * location widget (#662).
 *
 * A place is looked up only when asked for (Search, or Enter), never as it is
 * typed: Nominatim's usage policy forbids auto-complete on its API.
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
