/**
 * Simple View's image modes (#276).
 *
 * The reported bug was that the CV Gallery never received its upstream output,
 * and the chosen fix was to let Simple View display images from any frame and
 * retire that node. The case that could not work before is the first one here:
 * a GeoDataFrame of image URLs. `getMode` read `input.data.image_id`, a
 * DataFrame column map, so a GeoDataFrame - whose columns live under
 * `features[i].properties` - always fell through to a table.
 *
 * `behaviors.test.tsx` covers the same hook but asserts only that
 * `contentComponent` is defined, which is also true of the empty state. These
 * assert what actually rendered.
 */
import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { useSimpleVisBehavior, resolveImageColumnChoice, ALL_IMAGE_COLUMNS } from '../../../adapters/node/simpleVisBehavior';

const mockUpdateDataNode = jest.fn();

jest.mock('reactflow', () => ({ useEdges: () => [{ source: 'up', target: 'sv-1' }] }));
jest.mock('../../../providers/ProvenanceProvider', () => ({
  useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
jest.mock('../../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ workflowNameRef: { current: 'wf' }, updateDataNode: mockUpdateDataNode }),
}));
jest.mock('../../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock('../../../services/api', () => ({ fetchData: jest.fn() }));
jest.mock('../../../utils/backendUrl', () => ({ backendUrl: () => 'http://backend.test' }));
jest.mock('../../../utils/authApi', () => ({ getToken: () => 'tok-123' }));

const nodeState = { setOutput: jest.fn() } as any;

function Harness({ data }: { data: any }) {
  const { contentComponent } = useSimpleVisBehavior(data, nodeState);
  return <>{contentComponent}</>;
}

function nodeData(input: any, extra: any = {}) {
  return {
    nodeId: 'sv-1',
    input,
    outputCallback: jest.fn(),
    interactionsCallback: jest.fn(),
    ...extra,
  };
}

/** A GeoDataFrame the way the sandbox serialises one: a FeatureCollection. */
function geoFrame(properties: Record<string, unknown>[]) {
  return {
    dataType: 'geodataframe',
    data: {
      type: 'FeatureCollection',
      features: properties.map((props) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [0, 0] },
        properties: props,
      })),
    },
  };
}

const longBase64 = 'iVBORw0KGgo' + 'A'.repeat(80);

describe('Simple View image modes', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // jsdom ships neither; the overlay column takes the authenticated path,
    // which ImageCardGrid.test.tsx covers in detail.
    (global as any).fetch = jest
      .fn()
      .mockResolvedValue({ ok: true, blob: () => Promise.resolve(new Blob()) });
    (global as any).URL.createObjectURL = jest.fn(() => 'blob:stub');
    (global as any).URL.revokeObjectURL = jest.fn();
  });

  it('renders a GeoDataFrame of image URLs as images, not a table', async () => {
    const input = geoFrame([
      { image_url: 'https://example.test/a?size=640', image_id: 'CAoSL1', vegetation: 31.2 },
      { image_url: 'https://example.test/b?size=640', image_id: 'CAoSL2', vegetation: 12.7 },
    ]);
    await act(async () => {
      render(<Harness data={nodeData(input)} />);
    });
    expect(screen.getAllByRole('img')).toHaveLength(2);
    expect(screen.getByText('image_id: CAoSL1')).toBeInTheDocument();
  });

  it('renders a DataFrame of image URLs as images', async () => {
    const input = {
      dataType: 'dataframe',
      data: {
        image_url: { 0: 'https://example.test/a?size=640', 1: 'https://example.test/b?size=640' },
        label: { 0: 'leafy', 1: 'paved' },
      },
    };
    await act(async () => {
      render(<Harness data={nodeData(input)} />);
    });
    expect(screen.getAllByRole('img')).toHaveLength(2);
  });

  it('still renders the base64 image_content contract Image.json ships', async () => {
    const input = {
      dataType: 'dataframe',
      data: { image_id: { 0: 0, 1: 1 }, image_content: { 0: longBase64, 1: longBase64 } },
    };
    await act(async () => {
      render(<Harness data={nodeData(input)} />);
    });
    const imgs = screen.getAllByRole('img');
    expect(imgs).toHaveLength(2);
    expect(imgs[0]).toHaveAttribute('src', `data:image/png;base64,${longBase64}`);
  });

  it('flattens a row whose image cell holds a list', async () => {
    // The numpy-array-cell shape parseOutput emits: one row, two pictures.
    const input = {
      dataType: 'dataframe',
      data: { image_id: { 0: [0, 1] }, image_content: { 0: [longBase64, longBase64] } },
    };
    await act(async () => {
      render(<Harness data={nodeData(input)} />);
    });
    expect(screen.getAllByRole('img')).toHaveLength(2);
  });

  it('leaves a frame with no image column as a table', async () => {
    const input = geoFrame([{ name: 'Lincoln Park', shape_area: 4849 }]);
    await act(async () => {
      render(<Harness data={nodeData(input)} />);
    });
    expect(screen.queryAllByRole('img')).toHaveLength(0);
    expect(screen.getByRole('table')).toBeInTheDocument();
  });

  it('shows source and overlay side by side, with a picker to narrow', async () => {
    const input = geoFrame([
      {
        image_url: 'https://example.test/a?size=640',
        overlay_url: '/api/streetvision/inference/overlay/a.jpg',
        image_id: 'CAoSL1',
      },
    ]);
    await act(async () => {
      render(<Harness data={nodeData(input)} />);
    });
    // Two image columns, so both are drawn and the picker appears.
    const picker = screen.getByLabelText('Image column') as HTMLSelectElement;
    expect(picker.value).toBe(ALL_IMAGE_COLUMNS);
    expect(Array.from(picker.options).map((o) => o.value))
      .toEqual([ALL_IMAGE_COLUMNS, 'image_url', 'overlay_url']);
  });

  it('draws only the pinned column when the node carries a choice', async () => {
    const input = geoFrame([
      {
        image_url: 'https://example.test/a?size=640',
        overlay_url: 'https://example.test/a-overlay.png',
        image_id: 'CAoSL1',
      },
    ]);
    await act(async () => {
      render(<Harness data={nodeData(input, { simpleVis: { imageColumn: 'overlay_url' } })} />);
    });
    const imgs = screen.getAllByRole('img');
    expect(imgs).toHaveLength(1);
    expect(imgs[0]).toHaveAttribute('src', 'https://example.test/a-overlay.png');
  });

  it('falls back to every column when the pinned one is not in this frame', async () => {
    const input = geoFrame([{ image_url: 'https://example.test/a?size=640' }]);
    await act(async () => {
      render(<Harness data={nodeData(input, { simpleVis: { imageColumn: 'overlay_url' } })} />);
    });
    expect(screen.getAllByRole('img')).toHaveLength(1);
  });

  it('hides the picker when there is only one image column', async () => {
    const input = geoFrame([{ image_url: 'https://example.test/a?size=640' }]);
    await act(async () => {
      render(<Harness data={nodeData(input)} />);
    });
    expect(screen.queryByLabelText('Image column')).not.toBeInTheDocument();
  });
});

describe('Simple View with nothing to show', () => {
  it('renders the empty state, not an empty text payload', async () => {
    // A freshly dropped node carries `input: ''`. Rendering that as text put a
    // bare `""` in the box instead of the message saying what to wire in
    // (#224), which the empty-nodes-say-why walkthrough caught.
    await act(async () => {
      render(<Harness data={nodeData('')} />);
    });
    expect(document.querySelector('[data-curio-node-empty]')).toBeInTheDocument();
    expect(screen.queryByText('""')).not.toBeInTheDocument();
  });
});

describe('resolveImageColumnChoice', () => {
  it('defaults to all, and reads the persisted choice', () => {
    expect(resolveImageColumnChoice(undefined)).toBe(ALL_IMAGE_COLUMNS);
    expect(resolveImageColumnChoice({ simpleVis: { imageColumn: '  ' } })).toBe(ALL_IMAGE_COLUMNS);
    expect(resolveImageColumnChoice({ simpleVis: { imageColumn: 'overlay_url' } })).toBe('overlay_url');
  });
});
