/**
 * One broken subtree must not take the app with it (#201).
 *
 * There was no error boundary anywhere in the app, so a throw while rendering a
 * single node unmounted the whole React root: canvas, menus and every other
 * node gone, leaving a blank document. The reported trigger was an Autark node
 * on a browser without WebGPU, but any node that throws does the same thing,
 * which is why the containment is asserted separately from the WebGPU fix.
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import ErrorBoundary from '../../components/ErrorBoundary';

function Boom({ message = "kaboom" }: { message?: string }): React.ReactElement {
  throw new Error(message);
}

let consoleError: jest.SpyInstance;

beforeEach(() => {
  // React logs the caught error itself; silencing keeps the run readable
  // without hiding a genuine failure, since every assertion is on the DOM.
  consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  consoleError.mockRestore();
});

describe('ErrorBoundary', () => {
  test('renders its children when nothing throws', () => {
    render(
      <ErrorBoundary>
        <div>all good</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText('all good')).toBeInTheDocument();
  });

  test('contains a throwing child instead of unmounting the tree', () => {
    render(
      <ErrorBoundary>
        <Boom message="node exploded" />
      </ErrorBoundary>,
    );

    const alert = screen.getByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent('node exploded');
  });

  test('a sibling subtree still mounts — the blast radius is one boundary', () => {
    // This is the actual claim of the fix: the canvas around a broken node
    // keeps rendering. Two boundaries, only one of them tripped.
    render(
      <div>
        <ErrorBoundary label="node a">
          <Boom />
        </ErrorBoundary>
        <ErrorBoundary label="node b">
          <div>sibling still here</div>
        </ErrorBoundary>
      </div>,
    );

    expect(screen.getByText('sibling still here')).toBeInTheDocument();
    expect(screen.getAllByRole('alert')).toHaveLength(1);
  });

  test('a custom fallback replaces the default notice', () => {
    render(
      <ErrorBoundary fallback={(err) => <p>custom: {err.message}</p>}>
        <Boom message="specific" />
      </ErrorBoundary>,
    );

    expect(screen.getByText('custom: specific')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('reports the error to onError, with the label in the console line', () => {
    const onError = jest.fn();
    render(
      <ErrorBoundary label="node autk-1" onError={onError}>
        <Boom message="createShaderModule of undefined" />
      </ErrorBoundary>,
    );

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0]).toBeInstanceOf(Error);
    expect(onError.mock.calls[0][0].message).toBe('createShaderModule of undefined');
    // The label is what makes a console line attributable to a node id.
    expect(consoleError).toHaveBeenCalledWith(
      expect.stringContaining('node autk-1'),
      expect.anything(),
      expect.anything(),
    );
  });

  test('"Try again" re-renders the children once whatever broke them has changed (#271)', () => {
    let shouldThrow = true;
    function Flaky(): React.ReactElement {
      if (shouldThrow) throw new Error('first render only');
      return <div>recovered</div>;
    }
    render(
      <ErrorBoundary>
        <Flaky />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('first render only');

    shouldThrow = false;
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));

    expect(screen.getByText('recovered')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('an error with no message still renders something actionable', () => {
    render(
      <ErrorBoundary>
        <Boom message="" />
      </ErrorBoundary>,
    );

    expect(screen.getByRole('alert')).toHaveTextContent(
      'This part of the page could not be rendered.',
    );
  });
});
