import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { AgentDatasetCandidatesCard, composeConfirmationPrompt } from '../../components/agents/content/AgentDatasetCandidatesCard';
import type { AgentDatasetCandidateRow } from '../../api/agentsApi';

/**
 * The external lane used to mean exactly one thing: hand it to Node Builder.
 * A row Curio can actually download now says so, and composes a different
 * confirmation — while a row it cannot still goes to Node Builder, which is
 * the right answer for a source no provider covers.
 */

const external = (over: Partial<AgentDatasetCandidateRow> = {}): AgentDatasetCandidateRow => ({
  name: 'Bike Routes',
  sourceType: 'lake',
  ...over,
});

const catalogRow = (over: Partial<AgentDatasetCandidateRow> = {}): AgentDatasetCandidateRow => ({
  name: 'Chicago Boundary',
  sourceType: 'catalog',
  datasetId: 'data.urbanlab.chicago-boundary',
  ...over,
});

describe('composeConfirmationPrompt', () => {
  test('a downloadable row composes a download, not a handoff', () => {
    const prompt = composeConfirmationPrompt(
      [],
      [external({ acquirable: true, sourceId: 'lake.a.b@1', resourceId: 'abcd-1234' })]
    );
    expect(prompt).toContain('download into my Data Catalog');
    expect(prompt).toContain('lake.a.b@1/abcd-1234');
    expect(prompt).not.toContain('Node Builder');
  });

  test('a row without a coordinate still goes to Node Builder', () => {
    const prompt = composeConfirmationPrompt([], [external({ url: 'https://a.example/x' })]);
    expect(prompt).toContain('hand off to Node Builder');
    expect(prompt).not.toContain('download into my Data Catalog');
  });

  test('a row the runtime did not mark acquirable goes to Node Builder', () => {
    // The model may name a source; only the runtime says it can be acted on.
    const prompt = composeConfirmationPrompt(
      [],
      [external({ sourceId: 'lake.made.up@1', resourceId: 'x' })]
    );
    expect(prompt).toContain('hand off to Node Builder');
  });

  test('a mixed selection asks for both, in one prompt', () => {
    const prompt = composeConfirmationPrompt(
      [catalogRow()],
      [
        external({ acquirable: true, sourceId: 'lake.a.b@1', resourceId: 'r1' }),
        external({ name: 'Something Else', url: 'https://a.example/y' }),
      ]
    );
    expect(prompt).toContain('install from the Data Catalog');
    expect(prompt).toContain('download into my Data Catalog');
    expect(prompt).toContain('hand off to Node Builder');
  });

  test('nothing selected composes nothing', () => {
    expect(composeConfirmationPrompt([], [])).toBe('');
  });
});

describe('the Downloadable chip', () => {
  const renderCard = (rows: AgentDatasetCandidateRow[]) =>
    render(
      <AgentDatasetCandidatesCard
        part={{ type: 'datasetCandidates', lanes: { external: rows, catalog: [] } } as never}
      />
    );

  test('marks a row the runtime said can be downloaded', () => {
    renderCard([external({ acquirable: true, sourceId: 'lake.a.b@1', resourceId: 'r1' })]);
    expect(screen.getByText('Downloadable')).toBeInTheDocument();
  });

  test('is absent when the runtime did not say so', () => {
    renderCard([external({ url: 'https://a.example/x' })]);
    expect(screen.queryByText('Downloadable')).toBeNull();
  });
});
