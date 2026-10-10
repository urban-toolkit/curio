import React from "react";

import {
  acquireKey,
  type DiscoveryAcquireJob,
  type DiscoveryResource,
  type DiscoverySourceRow,
  type UseDiscoveryAcquireResult,
} from "../../services/discoveryCatalog";
import styles from "./DiscoveryAddDialog.module.css";
import { DiscoveryResourceRow } from "./DiscoveryResourceRow";
import { SourceParameterForm, answered, parameterProblem, type ParameterValues } from "./SourceParameterForm";

/**
 * A link-only source's page (Direct URL): paste a link to a file, and it is
 * downloaded into the Data Catalog like any portal's resource.
 *
 * The link is the resource id, the same contract the Dataset Finder's
 * candidate rows use, so a pasted link and a found one share one download
 * and one held lookup. Each link added here gets a row with its progress.
 *
 * A link to a GeoParquet file takes the source's Area: only the parts of the
 * file inside it are read, and the dataset is named after the file and the area.
 */

export interface DiscoveryLinkFormProps {
  source: DiscoverySourceRow;
  acquisition: UseDiscoveryAcquireResult;
  onViewDataset: (datasetId: string) => void;
}

/** The file name a link ends in, for the dataset's title. */
export function linkTitle(url: string): string {
  try {
    const last = new URL(url).pathname.split("/").filter(Boolean).pop();
    return last ? decodeURIComponent(last) : url;
  } catch {
    return url;
  }
}

/** Whether a link names a GeoParquet file, which an Area can narrow. */
export function isParquetLink(url: string): boolean {
  return linkTitle(url).toLowerCase().endsWith(".parquet");
}

export function DiscoveryLinkForm({ source, acquisition, onViewDataset }: DiscoveryLinkFormProps) {
  const [link, setLink] = React.useState("");
  const [links, setLinks] = React.useState<string[]>([]);
  const [values, setValues] = React.useState<ParameterValues>({});
  const trimmed = link.trim();
  const problem = trimmed && !trimmed.startsWith("https://") ? "The link must start with https://." : null;
  const parameters = React.useMemo(
    () => (trimmed && isParquetLink(trimmed) ? (source.parameters ?? []).filter((p) => p.type === "area") : []),
    [source.parameters, trimmed],
  );
  const areaProblem = parameterProblem(parameters, values);

  const add = (e: React.FormEvent) => {
    e.preventDefault();
    if (!trimmed || problem || areaProblem) return;
    const answers = answered(parameters, values);
    setLinks((all) => (all.includes(trimmed) ? all : [trimmed, ...all]));
    setLink("");
    setValues({});
    // With an Area, the server names the dataset after the file and the area.
    void acquisition.start(
      source.dirName,
      trimmed,
      Object.keys(answers).length > 0 ? { parameters: answers } : { title: linkTitle(trimmed) },
    );
  };

  const row = (url: string): DiscoveryResource => ({
    sourceId: source.sourceId,
    sourceName: source.name,
    resourceId: url,
    name: linkTitle(url),
    description: url,
    publisher: "",
    formats: [],
    updatedAt: null,
    landingUrl: null,
    sizeHint: null,
    acquirable: true,
    alreadyHeldDatasetId: null,
  });

  return (
    <div className={styles.form}>
      <form className={styles.field} onSubmit={add} aria-label="Add a file by its link">
        <label className={styles.fieldLabel} htmlFor="discovery-link">
          Link to a file
        </label>
        <div className={styles.range}>
          <input
            id="discovery-link"
            className={styles.input}
            type="url"
            placeholder="https://example.org/data/file.csv"
            value={link}
            onChange={(e) => setLink(e.target.value)}
          />
          <button
            type="submit"
            className={`${styles.modeBtn} ${styles.modeBtnActive}`}
            disabled={!trimmed || Boolean(problem) || Boolean(areaProblem)}
          >
            Download
          </button>
        </div>
        <p className={styles.hint}>
          It downloads into your Data Catalog as{" "}
          {source.capabilities.formats.map((f) => f.toUpperCase()).join(", ")}.
        </p>
        {problem ? <p className={styles.warning}>{problem}</p> : null}
        {parameters.length > 0 ? (
          <SourceParameterForm parameters={parameters} values={values} onChange={setValues} />
        ) : null}
        {areaProblem ? <p className={styles.warning}>{areaProblem}</p> : null}
      </form>
      {links.map((url) => (
        <DiscoveryResourceRow
          key={url}
          resource={row(url)}
          job={acquisition.jobs[acquireKey(source.dirName, url)] as DiscoveryAcquireJob | undefined}
          onViewDataset={onViewDataset}
          onCancel={() => acquisition.cancel(source.dirName, url)}
          onDismiss={() => {
            acquisition.dismiss(source.dirName, url);
            setLinks((all) => all.filter((x) => x !== url));
          }}
        />
      ))}
    </div>
  );
}

export default DiscoveryLinkForm;
