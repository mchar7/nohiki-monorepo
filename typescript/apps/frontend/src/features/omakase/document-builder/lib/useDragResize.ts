import { useEffect, useRef, useState } from 'react';

const SPLIT_LAYOUT_PERCENT: number = 100;
const MIN_PANE_WIDTH_PX: number = 200;
const INITIAL_SPLIT_PERCENT: number = SPLIT_LAYOUT_PERCENT / 2;
const DEFAULT_PANE_WIDTH: string = '50%';

/** Computes new pane percentages from a drag delta, clamped to min width. */
function computeDragWidths(
  container: HTMLDivElement,
  initialEditor: number,
  initialPreview: number,
  deltaX: number,
): { editorPercent: number; previewPercent: number } | null {
  const { width } = container.getBoundingClientRect();
  const newEditor = initialEditor + deltaX;
  const newPreview = initialPreview - deltaX;

  if (newEditor < MIN_PANE_WIDTH_PX || newPreview < MIN_PANE_WIDTH_PX) {
    return null;
  }

  return {
    editorPercent: (newEditor / width) * SPLIT_LAYOUT_PERCENT,
    previewPercent: (newPreview / width) * SPLIT_LAYOUT_PERCENT,
  };
}

/** Converts a percentage width string (e.g. "50%") to pixel width for a container. */
function percentToPixels(percentStr: string, containerWidth: number): number {
  return (Number.parseFloat(percentStr) / SPLIT_LAYOUT_PERCENT) * containerWidth;
}

interface DragRefs {
  readonly containerRef: React.RefObject<HTMLDivElement | null>;
  readonly dragStartX: React.RefObject<number>;
  readonly initialWidths: React.RefObject<{ editor: number; preview: number }>;
}

/** Captures initial pane pixel widths before starting a drag operation. */
function captureInitialWidths(refs: DragRefs, editorWidth: string, previewWidth: string): void {
  const container = refs.containerRef.current;
  if (container) {
    const rect = container.getBoundingClientRect();
    refs.initialWidths.current = {
      editor: percentToPixels(editorWidth, rect.width),
      preview: percentToPixels(previewWidth, rect.width),
    };
  }
}

interface DragListenerOptions {
  readonly isDragging: boolean;
  readonly refsRef: React.RefObject<DragRefs>;
  readonly setWidths: (editor: string, preview: string) => void;
  readonly setIsDragging: (v: boolean) => void;
}

/** Attaches mouse/touch drag listeners while dragging is active. */
function useDragListeners({
  isDragging,
  refsRef,
  setWidths,
  setIsDragging,
}: DragListenerOptions): void {
  useEffect(() => {
    if (!isDragging) {
      return;
    }
    const refs = refsRef.current;
    const apply = (clientX: number): void => {
      const container = refs.containerRef.current;
      if (!container) {
        return;
      }
      const result = computeDragWidths(
        container,
        refs.initialWidths.current.editor,
        refs.initialWidths.current.preview,
        clientX - refs.dragStartX.current,
      );
      if (result) {
        setWidths(`${result.editorPercent}%`, `${result.previewPercent}%`);
      }
    };
    const onMouseMove = (e: MouseEvent): void => apply(e.clientX);
    const onTouchMove = (e: TouchEvent): void => {
      e.preventDefault();
      const [touch] = e.touches;
      if (touch) {
        apply(touch.clientX);
      }
    };
    const stopDrag = (): void => setIsDragging(false);

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', stopDrag);
    document.addEventListener('touchmove', onTouchMove, { passive: false });
    document.addEventListener('touchend', stopDrag);
    return () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', stopDrag);
      document.removeEventListener('touchmove', onTouchMove);
      document.removeEventListener('touchend', stopDrag);
    };
  }, [isDragging, refsRef, setWidths, setIsDragging]);
}

interface DragResizeState {
  editorWidth: string;
  previewWidth: string;
  isDragging: boolean;
  containerRef: React.RefObject<HTMLDivElement | null>;
  startDrag: (e: React.MouseEvent) => void;
  startTouchDrag: (e: React.TouchEvent) => void;
  resetLayout: () => void;
}

/** Manages the drag-to-resize interaction between editor and preview panes. */
export function useDragResize(): DragResizeState {
  const [editorWidth, setEditorWidth] = useState(DEFAULT_PANE_WIDTH);
  const [previewWidth, setPreviewWidth] = useState(DEFAULT_PANE_WIDTH);
  const [isDragging, setIsDragging] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const dragStartX = useRef<number>(0);
  const initialWidths = useRef({ editor: INITIAL_SPLIT_PERCENT, preview: INITIAL_SPLIT_PERCENT });
  const refsRef = useRef<DragRefs>({ containerRef, dragStartX, initialWidths });

  const initDrag = (clientX: number): void => {
    setIsDragging(true);
    dragStartX.current = clientX;
    captureInitialWidths(refsRef.current, editorWidth, previewWidth);
  };

  const startDrag = (e: React.MouseEvent): void => {
    e.preventDefault();
    initDrag(e.clientX);
  };

  const startTouchDrag = (e: React.TouchEvent): void => {
    const touch = e.touches.item(0);
    if (touch) {
      initDrag(touch.clientX);
    }
  };

  const resetLayout = (): void => {
    setEditorWidth(DEFAULT_PANE_WIDTH);
    setPreviewWidth(DEFAULT_PANE_WIDTH);
  };

  const setWidths = (editor: string, preview: string): void => {
    setEditorWidth(editor);
    setPreviewWidth(preview);
  };

  useDragListeners({ isDragging, refsRef, setWidths, setIsDragging });

  return {
    editorWidth,
    previewWidth,
    isDragging,
    containerRef,
    startDrag,
    startTouchDrag,
    resetLayout,
  };
}
