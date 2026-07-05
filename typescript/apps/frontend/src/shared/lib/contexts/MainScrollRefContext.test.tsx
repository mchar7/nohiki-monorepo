import { render, screen } from '@testing-library/react';
import type { JSX } from 'react';
import { useRef } from 'react';
import { describe, expect, vi } from 'vitest';
import { MainScrollRefContext, useMainScrollRef } from './MainScrollRefContext.ts';

function TestConsumer(): JSX.Element {
  const ref = useMainScrollRef();
  return <span data-testid="has-ref">{(ref !== null).toString()}</span>;
}

function TestProvider({ children }: { readonly children: React.ReactNode }): JSX.Element {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <MainScrollRefContext.Provider value={ref}>
      <div ref={ref}>{children}</div>
    </MainScrollRefContext.Provider>
  );
}

describe('MainScrollRefContext', () => {
  describe('useMainScrollRef', () => {
    test('throws when used outside provider', () => {
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {
        /* suppress test output */
      });

      expect(() => {
        render(<TestConsumer />);
      }).toThrow('useMainScrollRef must be used within a MainScrollRefContext.Provider');

      consoleError.mockRestore();
    });

    test('returns the ref when used inside provider', () => {
      render(
        <TestProvider>
          <TestConsumer />
        </TestProvider>,
      );

      expect(screen.getByTestId('has-ref')).toHaveTextContent('true');
    });
  });
});
