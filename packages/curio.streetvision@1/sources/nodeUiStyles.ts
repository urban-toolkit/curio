import type { CSSProperties } from 'react';

/** Shared presentation for Street Vision and connected editor node bodies. */
export const nodeUiStyles: Record<string, CSSProperties> = {
  root: {
    padding: '12px 14px', fontFamily: '"Roboto","Helvetica","Arial",sans-serif',
    fontSize: 13, color: '#333', display: 'flex', flexDirection: 'column', gap: 10,
  },
  header: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 },
  logo: {
    width: 28, height: 28, borderRadius: 6,
    background: 'linear-gradient(135deg,#3b82f6,#60a5fa)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    color: '#fff', fontSize: 14, fontWeight: 700, flexShrink: 0,
  },
  title: { fontSize: 14, fontWeight: 600, color: '#1a1a2e', lineHeight: 1.2 },
  sub: { fontSize: 10, color: '#888', marginTop: 1 },
  row: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#666' },
  dot: { width: 8, height: 8, borderRadius: '50%', flexShrink: 0 },
  input: {
    width: '100%', padding: '7px 10px', border: '1px solid #e2e8f0', borderRadius: 6,
    fontSize: 12, outline: 'none', boxSizing: 'border-box',
  },
  btn: {
    padding: '8px 12px', border: 'none', borderRadius: 8, fontSize: 12,
    fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center',
    justifyContent: 'center', gap: 6, transition: 'all 0.15s', width: '100%',
  },
  btnPrimary: { background: 'linear-gradient(135deg,#3b82f6,#2563eb)', color: '#fff' },
  btnSecondary: { background: '#f1f5f9', color: '#334155', border: '1px solid #e2e8f0' },
  btnDisabled: { background: '#f3f4f6', color: '#9ca3af', border: '1px solid #e5e7eb', cursor: 'not-allowed' },
  card: { background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: '10px 12px', fontSize: 12 },
  label: { fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: '#94a3b8', letterSpacing: 1, marginBottom: 4 },
  helper: { fontSize: 11, color: '#64748b', marginTop: 4 },
  warn: { color: '#92400e', background: '#fef9c3', borderColor: '#fde68a', fontSize: 11 },
  err: { color: '#991b1b', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 6, padding: '6px 8px', fontSize: 11 },
};
