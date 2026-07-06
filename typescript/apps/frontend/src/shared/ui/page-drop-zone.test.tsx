import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, vi } from 'vitest';
import { PageDropZone } from './page-drop-zone.tsx';

// PageDropZone reads `event.dataTransfer.types`, `event.dataTransfer.files`,
// and `event.dataTransfer.dropEffect`. @testing-library/react's `fireEvent`
// init parameter accepts `{}` (anything), so the helpers below return the
// minimal structural shape the component reads. Inferred return types keep
// the test honest about which fields are actually used and remove the need
// to claim the helpers produce full DOM `DataTransfer` / `FileList`
// instances (which jsdom cannot construct anyway).

function createMockFileList(files: readonly File[]) {
  return Object.assign([...files], {
    item: (index: number): File | null => files[index] ?? null,
  });
}

function createDragEvent(types: readonly string[] = ['Files']) {
  return {
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
    dataTransfer: {
      types: [...types],
      files: createMockFileList([]),
      dropEffect: 'none',
    },
  };
}

function createDropEvent(files: readonly File[]) {
  return {
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
    dataTransfer: {
      files: createMockFileList(files),
      types: ['Files'],
      dropEffect: 'none',
    },
  };
}

function getDropZoneWrapper(contentText: string): HTMLElement {
  const el = screen.getByText(contentText).parentElement;
  if (!el) {
    throw new Error(`Could not find parent element of "${contentText}"`);
  }
  return el;
}

function getDropZoneWrapperByTestId(testId: string): HTMLElement {
  const el = screen.getByTestId(testId).parentElement;
  if (!el) {
    throw new Error(`Could not find parent element of testId "${testId}"`);
  }
  return el;
}

const OVERLAY_TEST_ID = 'page-drop-zone-overlay';

describe('PageDropZone - rendering', () => {
  test('renders children without overlay by default', () => {
    render(
      <PageDropZone onDrop={vi.fn()}>
        <p>Page content</p>
      </PageDropZone>,
    );

    expect(screen.getByText('Page content')).toBeInTheDocument();
    expect(screen.queryByTestId(OVERLAY_TEST_ID)).not.toBeInTheDocument();
  });

  test('overlay has correct aria-label', () => {
    render(
      <PageDropZone onDrop={vi.fn()}>
        <p>Page content</p>
      </PageDropZone>,
    );

    const zone = getDropZoneWrapper('Page content');
    fireEvent.dragEnter(zone, createDragEvent());
    expect(screen.getByTestId(OVERLAY_TEST_ID)).toHaveAttribute('aria-label', 'File drop zone');
  });
});

describe('PageDropZone - drag interactions', () => {
  test('shows overlay on dragenter with file types', () => {
    render(
      <PageDropZone onDrop={vi.fn()}>
        <p>Page content</p>
      </PageDropZone>,
    );

    const zone = getDropZoneWrapper('Page content');
    fireEvent.dragEnter(zone, createDragEvent());
    expect(screen.getByTestId(OVERLAY_TEST_ID)).toBeInTheDocument();
    expect(screen.getByText('Drop to upload')).toBeInTheDocument();
  });

  test('hides overlay on dragleave', () => {
    render(
      <PageDropZone onDrop={vi.fn()}>
        <p>Page content</p>
      </PageDropZone>,
    );

    const zone = getDropZoneWrapper('Page content');
    fireEvent.dragEnter(zone, createDragEvent());
    expect(screen.getByTestId(OVERLAY_TEST_ID)).toBeInTheDocument();

    fireEvent.dragLeave(zone, createDragEvent());
    expect(screen.queryByTestId(OVERLAY_TEST_ID)).not.toBeInTheDocument();
  });

  test('handles nested drag enter/leave correctly', () => {
    render(
      <PageDropZone onDrop={vi.fn()}>
        <div data-testid="child">
          <span>Nested</span>
        </div>
      </PageDropZone>,
    );

    const zone = getDropZoneWrapperByTestId('child');
    const child = screen.getByTestId('child');

    fireEvent.dragEnter(zone, createDragEvent());
    fireEvent.dragEnter(child, createDragEvent());
    expect(screen.getByTestId(OVERLAY_TEST_ID)).toBeInTheDocument();

    fireEvent.dragLeave(child, createDragEvent());
    expect(screen.getByTestId(OVERLAY_TEST_ID)).toBeInTheDocument();

    fireEvent.dragLeave(zone, createDragEvent());
    expect(screen.queryByTestId(OVERLAY_TEST_ID)).not.toBeInTheDocument();
  });

  test('prevents default browser behavior on dragover', () => {
    render(
      <PageDropZone onDrop={vi.fn()}>
        <p>Page content</p>
      </PageDropZone>,
    );

    const zone = getDropZoneWrapper('Page content');
    const prevented = fireEvent.dragOver(zone, createDragEvent());
    expect(prevented).toBe(false);
  });
});

describe('PageDropZone - drop behavior', () => {
  test('hides overlay and calls onDrop on file drop', () => {
    const onDrop = vi.fn();
    const testFile = new File(['content'], 'resume.pdf', { type: 'application/pdf' });

    render(
      <PageDropZone onDrop={onDrop}>
        <p>Page content</p>
      </PageDropZone>,
    );

    const zone = getDropZoneWrapper('Page content');
    fireEvent.dragEnter(zone, createDragEvent());
    expect(screen.getByTestId(OVERLAY_TEST_ID)).toBeInTheDocument();

    fireEvent.drop(zone, createDropEvent([testFile]));
    expect(screen.queryByTestId(OVERLAY_TEST_ID)).not.toBeInTheDocument();
    expect(onDrop).toHaveBeenCalledOnce();
    expect(onDrop.mock.calls[0]?.[0]).toHaveLength(1);
  });

  test('does not call onDrop when no files are dropped', () => {
    const onDrop = vi.fn();

    render(
      <PageDropZone onDrop={onDrop}>
        <p>Page content</p>
      </PageDropZone>,
    );

    const zone = getDropZoneWrapper('Page content');
    fireEvent.drop(zone, createDropEvent([]));
    expect(onDrop).not.toHaveBeenCalled();
  });
});

describe('PageDropZone - disabled state', () => {
  test('does not show overlay when disabled', () => {
    render(
      <PageDropZone onDrop={vi.fn()} disabled={true}>
        <p>Page content</p>
      </PageDropZone>,
    );

    const zone = getDropZoneWrapper('Page content');
    fireEvent.dragEnter(zone, createDragEvent());
    expect(screen.queryByTestId(OVERLAY_TEST_ID)).not.toBeInTheDocument();
  });

  test('does not call onDrop when disabled', () => {
    const onDrop = vi.fn();
    const testFile = new File(['content'], 'resume.pdf', { type: 'application/pdf' });

    render(
      <PageDropZone onDrop={onDrop} disabled={true}>
        <p>Page content</p>
      </PageDropZone>,
    );

    const zone = getDropZoneWrapper('Page content');
    fireEvent.drop(zone, createDropEvent([testFile]));
    expect(onDrop).not.toHaveBeenCalled();
  });
});
