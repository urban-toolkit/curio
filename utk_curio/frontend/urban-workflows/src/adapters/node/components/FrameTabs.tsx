import React from 'react';
import Nav from 'react-bootstrap/Nav';

/**
 * The tab strip of a node that shows each frame of its input as a tab: a Data
 * Pool's (hook/useTableData), and Simple View's for a dict of frames. A tab is
 * named after its frame's `layerName`, a dict's key or an Autark node's table,
 * else by its place.
 */

/** A tab's title: its frame's `layerName`, else "Tab <n>". */
export function frameTabTitle(entry: unknown, index: number): string {
  const name = entry && typeof entry === 'object' ? (entry as { layerName?: unknown }).layerName : undefined;
  return name ? String(name) : `Tab ${index + 1}`;
}

interface FrameTabsProps {
  /** The frames, a tab each, in order. */
  tabs: readonly unknown[];
  /** The open tab's place, as a string. */
  activeKey: string;
  onSelect: (key: string) => void;
  testId: string;
}

export default function FrameTabs({ tabs, activeKey, onSelect, testId }: FrameTabsProps) {
  return (
    <Nav
      variant="tabs"
      activeKey={activeKey}
      onSelect={(k) => onSelect(k || '0')}
      className="mb-3 nowheel"
      // nowrap + overflowX keeps the strip one row tall regardless of table
      // count, so adding tables never steals height from the table below.
      // overflowY hidden: a tab's -1px bottom margin would otherwise make
      // the strip scroll vertically by one pixel, with a scrollbar.
      // `nowheel` stops React Flow swallowing the scroll (#156).
      style={{ flexShrink: 0, flexWrap: 'nowrap', overflowX: 'auto', overflowY: 'hidden' }}
      data-testid={testId}
    >
      {tabs.map((entry, index) => (
        <Nav.Item key={index}>
          <Nav.Link eventKey={index.toString()}>{frameTabTitle(entry, index)}</Nav.Link>
        </Nav.Item>
      ))}
    </Nav>
  );
}
