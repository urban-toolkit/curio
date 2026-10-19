import type { CSSProperties } from 'react';

/** Package-local presentation using the same tokens as Curio's built-in node bodies. */
export const sidewalkNodeStyles: Record<string, CSSProperties> = {
  body: {
    display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0,
    boxSizing: 'border-box', gap: 6, padding: '6px 0',
    fontFamily: 'var(--curio-font-family)', fontSize: 'var(--curio-font-size-sm)',
    color: 'var(--curio-text-primary)', background: 'var(--curio-card-bg)',
  },
  row: { display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 6 },
  field: {
    display: 'flex', flexDirection: 'column', gap: 3,
    fontSize: 'var(--curio-font-size-xs)', color: 'var(--curio-text-secondary)',
  },
  input: {
    boxSizing: 'border-box', minWidth: 0, minHeight: 28, padding: '3px 8px',
    fontFamily: 'inherit', fontSize: 'var(--curio-font-size-sm)',
    border: '1px solid var(--curio-border-strong)', borderRadius: 'var(--curio-radius-sm)',
    background: 'var(--curio-card-bg)', color: 'var(--curio-text-primary)',
  },
  button: {
    minHeight: 26, padding: '2px 10px', fontFamily: 'inherit',
    fontSize: 'var(--curio-font-size-xs)', lineHeight: '20px',
    border: '1px solid var(--curio-border-strong)', borderRadius: 'var(--curio-radius-pill)',
    background: 'var(--curio-card-bg)', color: 'var(--curio-text-primary)', cursor: 'pointer',
  },
  primaryButton: {
    minHeight: 26, padding: '2px 12px', fontFamily: 'inherit',
    fontSize: 'var(--curio-font-size-xs)', fontWeight: 600, lineHeight: '20px',
    border: '1px solid var(--curio-top-bar-bg)', borderRadius: 'var(--curio-radius-pill)',
    background: 'var(--curio-top-bar-bg)', color: 'var(--curio-text-on-dark)', cursor: 'pointer',
  },
  disabledButton: {
    background: 'var(--curio-surface-muted)', borderColor: 'var(--curio-border)',
    color: 'var(--curio-text-secondary)', cursor: 'default',
  },
  helper: { margin: 0, fontSize: 'var(--curio-font-size-xs)', color: 'var(--curio-text-secondary)' },
  panel: {
    border: '1px solid var(--curio-border)', borderRadius: 'var(--curio-radius-md)',
    background: 'var(--curio-surface-muted)', padding: '6px 8px',
  },
  status: { margin: 0, fontSize: 'var(--curio-font-size-xs)', color: 'var(--curio-text-secondary)' },
  warning: {
    margin: 0, padding: '5px 8px', maxHeight: 48, overflow: 'auto',
    fontSize: 'var(--curio-font-size-xs)', color: 'var(--curio-warning-text)',
    background: 'var(--curio-warning-bg)', borderRadius: 'var(--curio-radius-sm)',
  },
  error: {
    margin: 0, padding: '5px 8px', maxHeight: 48, overflow: 'auto',
    fontSize: 'var(--curio-font-size-xs)', color: 'var(--curio-danger-text)',
    background: 'var(--curio-danger-bg)', borderRadius: 'var(--curio-radius-sm)',
  },
};
