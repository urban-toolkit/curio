import React, { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import logo from "assets/curio-2.png";

import {
  fetchMonitor,
  fetchMonitorErrors,
  fetchMonitorStorage,
  type MonitorErrorsPayload,
  type MonitorPayload,
  type MonitorStoragePayload,
} from "../../api/monitorApi";
import AppSectionTabs from "../../components/layout/AppSectionTabs";
import { GlobalPageHeader } from "../../components/layout/GlobalPageHeader";
import VersionBadge from "../../components/VersionBadge";
import useMonitorPoll from "../../hook/useMonitorPoll";
import { useUserContext } from "../../providers/UserProvider";
import {
  copyText,
  downloadJson,
  formatBytes,
  formatDuration,
  toMarkdown,
} from "../../utils/diagnosticsBundle";
import ErrorLogPanel from "./ErrorLogPanel";
import { DurationHistogram, StoreSizeHistogram } from "./MonitorCharts";
import { Chip, Meter, StatTile } from "./StatTile";
import styles from "./MonitorPage.module.css";

const FAST_POLL_MS = 5000;
// The storage walk is the one expensive call; the backend caches it for the
// same 60s, so polling faster would only ever return the same cached body.
const STORAGE_POLL_MS = 60000;

/**
 * The deployment monitor.
 *
 * Public and unauthenticated, and present on every instance rather than only
 * under --deploy: the error log is as useful on a laptop as on a server.
 *
 * Because it is public, an anonymous visitor must not be shown the signed-in
 * chrome. GlobalPageHeader renders an avatar, a name and a Sign out button
 * whenever auth is enabled, which on a deployed instance is always, so this
 * page falls back to a logo-only bar when there is no user.
 */
export const MonitorPage: React.FC = () => {
  const { user } = useUserContext();
  const [paused, setPaused] = useState(false);
  const [copied, setCopied] = useState(false);

  const monitor = useMonitorPoll<MonitorPayload>(fetchMonitor, FAST_POLL_MS, paused);
  const errors = useMonitorPoll<MonitorErrorsPayload>(
    fetchMonitorErrors,
    FAST_POLL_MS,
    paused
  );
  const storage = useMonitorPoll<MonitorStoragePayload>(
    fetchMonitorStorage,
    STORAGE_POLL_MS,
    paused
  );

  const bundle = {
    monitor: monitor.data,
    storage: storage.data,
    errors: errors.data,
  };

  const onCopy = useCallback(async () => {
    const ok = await copyText(toMarkdown(bundle));
    setCopied(ok);
    window.setTimeout(() => setCopied(false), 2000);
  }, [bundle]);

  const m = monitor.data;
  const backend = m?.execution.backend;
  const sandbox = m?.execution.sandbox;
  const hw = m?.hardware;
  const stale = monitor.error != null;

  return (
    <div className={styles.pageShell}>
      {user ? (
        <>
          <GlobalPageHeader />
          <AppSectionTabs />
        </>
      ) : (
        <header className={styles.publicBar}>
          <Link to="/" className={styles.publicBarLink}>
            <img src={logo} alt="Curio" className={styles.publicBarLogo} />
          </Link>
          <span className={styles.publicBarTitle}>Monitor</span>
        </header>
      )}

      <div className={styles.scroll}>
        <div className={styles.toolbar}>
          <div className={styles.toolbarStatus}>
            <span className={styles.updated}>
              {monitor.lastUpdatedAt
                ? `Last updated ${monitor.lastUpdatedAt.toLocaleTimeString()}`
                : "Loading…"}
            </span>
            {stale ? (
              <span className={styles.staleBanner} role="status">
                Could not reach the backend; showing the last values received.
              </span>
            ) : null}
          </div>
          <div className={styles.toolbarActions}>
            <button
              type="button"
              className={styles.button}
              onClick={() => setPaused((p) => !p)}
              aria-pressed={paused}
            >
              {paused ? "Resume" : "Pause"}
            </button>
            <button type="button" className={styles.button} onClick={onCopy}>
              {copied ? "Copied" : "Copy diagnostics"}
            </button>
            <button
              type="button"
              className={styles.button}
              onClick={() => downloadJson(bundle)}
            >
              Download
            </button>
          </div>
        </div>

        <section className={styles.section} aria-labelledby="mon-deployment">
          <h2 id="mon-deployment" className={styles.heading}>
            Deployment
          </h2>
          <div className={styles.chipGrid} data-testid="monitor-deployment">
            <Chip label="Version" value={m?.deployment.version ?? "…"} />
            <Chip
              label="Isolation"
              value={
                m
                  ? `${m.deployment.isolation} / ${m.deployment.isolationActive}`
                  : "…"
              }
              tone={
                m?.deployment.isolationActive === "fork"
                  ? "good"
                  : m?.deployment.isolationActive === "off"
                  ? "warn"
                  : "neutral"
              }
            />
            <Chip
              label="Authentication"
              value={m?.deployment.authEnabled ? "on" : "off"}
              tone={m?.deployment.authEnabled ? "good" : "neutral"}
            />
            <Chip label="Projects" value={m?.deployment.projectsEnabled ? "on" : "off"} />
            <Chip label="Guest login" value={m?.deployment.guestLoginAllowed ? "allowed" : "off"} />
            <Chip label="Shared installs" value={m?.deployment.sharedInstallsAllowed ? "allowed" : "off"} />
            <Chip label="Collaboration" value={m?.deployment.collabEnabled ? "on" : "off"} />
            <Chip label="Exec account" value={m?.deployment.execUserConfigured ? "configured" : "none"} />
            <Chip label="LLM provider" value={m?.deployment.llmProviderConfigured ? "configured" : "none"} />
            <Chip label="Environment" value={m?.deployment.env ?? "…"} />
            <Chip label="Platform" value={m?.deployment.platform ?? "…"} />
            <Chip label="Python" value={m?.deployment.pythonVersion ?? "…"} />
            <Chip label="Uptime" value={formatDuration(m?.uptimeSeconds)} />
          </div>
        </section>

        <section className={styles.section} aria-labelledby="mon-hardware">
          <h2 id="mon-hardware" className={styles.heading}>
            Hardware
          </h2>
          <div className={styles.tileGrid} data-testid="monitor-hardware">
            <StatTile
              label="CPU"
              value={hw?.cpu.logicalCores ?? "n/a"}
              sub={
                hw
                  ? `${hw.cpu.model}${
                      hw.cpu.physicalCores
                        ? ` · ${hw.cpu.physicalCores} physical`
                        : ""
                    }`
                  : "logical cores"
              }
            />
            <StatTile
              label="Memory"
              value={formatBytes(hw?.memory.totalBytes)}
              sub={`${formatBytes(hw?.memory.availableBytes)} available`}
              tone={(hw?.memory.usedPercent ?? 0) > 90 ? "danger" : "neutral"}
            />
            <StatTile
              label="Load (1m)"
              value={hw?.load.avg1m ?? "n/a"}
              sub={
                hw?.load.perCore != null
                  ? `${hw.load.perCore} per core`
                  : "not available on this platform"
              }
              tone={(hw?.load.perCore ?? 0) > 1 ? "warn" : "neutral"}
            />
            <StatTile
              label="Process memory"
              value={formatBytes(hw?.processes.backendRssBytes)}
              sub={`sandbox ${formatBytes(hw?.processes.sandboxRssBytes)}`}
            />
          </div>
          <div className={styles.split}>
            <div className={styles.card}>
              <Meter
                label="CPU in use"
                value={hw?.cpu.usagePercent ?? 0}
                max={100}
                caption={
                  hw?.cpu.usagePercent != null
                    ? `${hw.cpu.usagePercent}%`
                    : "sampling"
                }
                tone={(hw?.cpu.usagePercent ?? 0) > 90 ? "danger" : "neutral"}
              />
              <Meter
                label="Memory in use"
                value={hw?.memory.usedPercent ?? 0}
                max={100}
                caption={
                  hw?.memory.usedPercent != null
                    ? `${hw.memory.usedPercent}%`
                    : "unknown"
                }
                tone={(hw?.memory.usedPercent ?? 0) > 90 ? "danger" : "neutral"}
              />
              {hw?.memory.swapTotalBytes ? (
                <Meter
                  label="Swap in use"
                  value={hw.memory.swapUsedBytes ?? 0}
                  max={hw.memory.swapTotalBytes}
                  caption={`${formatBytes(hw.memory.swapUsedBytes)} of ${formatBytes(
                    hw.memory.swapTotalBytes
                  )}`}
                  tone="neutral"
                />
              ) : null}
            </div>
            <div className={styles.card}>
              <h3 className={styles.subHeading}>Load average</h3>
              <table className={styles.table}>
                <tbody>
                  <tr>
                    <td>1 minute</td>
                    <td className={styles.num}>{hw?.load.avg1m ?? "n/a"}</td>
                  </tr>
                  <tr>
                    <td>5 minutes</td>
                    <td className={styles.num}>{hw?.load.avg5m ?? "n/a"}</td>
                  </tr>
                  <tr>
                    <td>15 minutes</td>
                    <td className={styles.num}>{hw?.load.avg15m ?? "n/a"}</td>
                  </tr>
                  <tr>
                    <td>Architecture</td>
                    <td className={styles.num}>{hw?.cpu.arch ?? "n/a"}</td>
                  </tr>
                  {hw?.cpu.maxFrequencyMhz ? (
                    <tr>
                      <td>Max frequency</td>
                      <td className={styles.num}>{hw.cpu.maxFrequencyMhz} MHz</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className={styles.section} aria-labelledby="mon-execution">
          <h2 id="mon-execution" className={styles.heading}>
            Execution
          </h2>
          <div className={styles.tileGrid} data-testid="monitor-execution">
            <StatTile
              hero
              label="Node runs"
              value={backend?.total ?? "n/a"}
              sub={`${backend?.ok ?? 0} ok · ${backend?.error ?? 0} failed`}
            />
            <StatTile
              label="In flight"
              value={backend?.inFlight ?? "n/a"}
              sub={`${backend?.python ?? 0} python · ${backend?.javascript ?? 0} js`}
            />
            <StatTile
              label="Median run"
              value={backend?.durations.p50Ms != null ? `${backend.durations.p50Ms} ms` : "n/a"}
              sub={`p90 ${backend?.durations.p90Ms ?? "n/a"} ms · p99 ${backend?.durations.p99Ms ?? "n/a"} ms`}
            />
            <StatTile
              label="Node types"
              value={backend?.distinctNodeTypes ?? "n/a"}
              sub={backend?.lastExecutionAt ? `last run ${backend.lastExecutionAt}` : "no runs yet"}
            />
          </div>

          <div className={styles.split}>
            <div className={styles.card}>
              <h3 className={styles.subHeading}>Run duration</h3>
              {backend ? (
                <DurationHistogram buckets={backend.durations.buckets} />
              ) : (
                <p className={styles.empty}>Loading…</p>
              )}
              <Meter
                label="Failure rate"
                value={backend?.error ?? 0}
                max={backend?.total || 1}
                caption={`${backend?.error ?? 0} of ${backend?.total ?? 0}`}
                tone={
                  backend && backend.total > 0 && backend.error / backend.total > 0.25
                    ? "danger"
                    : "neutral"
                }
              />
            </div>

            <div className={styles.card}>
              <h3 className={styles.subHeading}>Sandbox</h3>
              {sandbox?.reachable ? (
                <>
                  <Meter
                    label="Isolated slots in use"
                    value={sandbox.slotsInUse ?? 0}
                    max={sandbox.parallelism ?? 1}
                    caption={`${sandbox.slotsInUse ?? 0} / ${sandbox.parallelism ?? "?"}`}
                  />
                  <div className={styles.chipGrid}>
                    <Chip label="Zygote" value={sandbox.zygoteRunning ? "running" : "stopped"}
                          tone={sandbox.zygoteRunning ? "good" : "warn"} />
                    <Chip label="Memory limit" value={`${sandbox.memoryLimitMb ?? "?"} MB`} />
                    <Chip label="CPU limit" value={`${sandbox.cpuSecondsLimit ?? "?"} s`} />
                    <Chip label="Wall timeout" value={`${sandbox.wallTimeoutSeconds ?? "?"} s`} />
                  </div>
                  <h4 className={styles.subHeading}>Child exits</h4>
                  <table className={styles.table}>
                    <tbody>
                      {Object.entries(sandbox.childDeaths ?? {}).map(([reason, n]) => (
                        <tr key={reason}>
                          <td>{reason}</td>
                          <td className={styles.num}>{n}</td>
                        </tr>
                      ))}
                      {Object.keys(sandbox.childDeaths ?? {}).length === 0 ? (
                        <tr>
                          <td colSpan={2} className={styles.empty}>
                            No abnormal exits since launch.
                          </td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </>
              ) : (
                <p className={styles.empty}>
                  The sandbox is not answering. Node execution is unavailable, but
                  everything else on this page is current.
                </p>
              )}
            </div>
          </div>
        </section>

        <section className={styles.section} aria-labelledby="mon-accounts">
          <h2 id="mon-accounts" className={styles.heading}>
            Accounts and content
          </h2>
          <div className={styles.tileGrid} data-testid="monitor-accounts">
            <StatTile
              label="Accounts"
              value={m?.accounts.total ?? "n/a"}
              sub={`${m?.accounts.registered ?? 0} registered · ${m?.accounts.guest ?? 0} guest`}
            />
            <StatTile
              label="Active sessions"
              value={m?.accounts.sessions.active ?? "n/a"}
              sub={`${m?.accounts.sessions.seenLast5m ?? 0} seen in 5 min`}
            />
            <StatTile
              label="Failed sign-ins"
              value={m?.accounts.signIn.failure ?? "n/a"}
              sub={`${m?.accounts.signIn.distinctSources ?? 0} sources in ${m?.accounts.signIn.windowMinutes ?? 60} min`}
              tone={(m?.accounts.signIn.failure ?? 0) > 20 ? "warn" : "neutral"}
            />
            <StatTile
              label="Projects"
              value={m?.content.projects.total ?? "n/a"}
              sub={`${m?.content.projects.openedLast24h ?? 0} opened in 24h`}
            />
            <StatTile
              label="Datasets"
              value={m?.content.datasets.total ?? "n/a"}
              sub={`${m?.content.datasets.imported ?? 0} imported · ${m?.content.datasets.computed ?? 0} computed`}
            />
            <StatTile
              label="Cached outputs"
              value={m?.content.execCacheEntries ?? "n/a"}
              sub="exec cache entries"
            />
          </div>
        </section>

        <section className={styles.section} aria-labelledby="mon-storage">
          <h2 id="mon-storage" className={styles.heading}>
            Storage
          </h2>
          <div className={styles.split} data-testid="monitor-storage">
            <div className={styles.card}>
              <h3 className={styles.subHeading}>User stores</h3>
              {storage.data ? (
                <>
                  <StoreSizeHistogram buckets={storage.data.userStores.buckets} />
                  <p className={styles.caption}>
                    {formatBytes(storage.data.userStores.totalBytes)} across{" "}
                    {storage.data.userStores.count} stores · largest{" "}
                    {formatBytes(storage.data.userStores.largestBytes)}
                    {storage.data.truncated ? " · measurement truncated" : ""}
                  </p>
                </>
              ) : (
                <p className={styles.empty}>Loading…</p>
              )}
            </div>
            <div className={styles.card}>
              <h3 className={styles.subHeading}>By area</h3>
              <table className={styles.table}>
                <tbody>
                  {(storage.data?.breakdown ?? []).map((row) => (
                    <tr key={row.area}>
                      <td>{row.area}</td>
                      <td className={styles.num}>{formatBytes(row.bytes)}</td>
                      <td className={styles.num}>{row.files} files</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {storage.data ? (
                <Meter
                  label="Disk used"
                  value={
                    (storage.data.disk.totalBytes ?? 0) -
                    (storage.data.disk.freeBytes ?? 0)
                  }
                  max={storage.data.disk.totalBytes ?? 1}
                  caption={`${formatBytes(storage.data.disk.freeBytes)} free`}
                />
              ) : null}
            </div>
          </div>
        </section>

        <section className={styles.section} aria-labelledby="mon-errors">
          <h2 id="mon-errors" className={styles.heading}>
            Recent errors
          </h2>
          <ErrorLogPanel
            errors={errors.data?.errors ?? []}
            droppedClient={errors.data?.droppedClient ?? 0}
            loading={errors.loading}
          />
        </section>
      </div>

      <VersionBadge />
    </div>
  );
};

export default MonitorPage;
