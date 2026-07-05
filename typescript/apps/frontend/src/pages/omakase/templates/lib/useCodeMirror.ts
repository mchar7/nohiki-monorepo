import { EditorState, type Extension } from '@codemirror/state';
import { EditorView, placeholder as placeholderExtension, type ViewUpdate } from '@codemirror/view';
import { type RefObject, useEffect, useRef } from 'react';

interface UseCodeMirrorOptions {
  value: string;
  onChange?: ((value: string) => void) | undefined;
  extensions?: Extension[] | undefined;
  placeholder?: string | undefined;
}

/** Build the extensions array including placeholder and update listener */
function buildExtensions(
  updateListener: Extension,
  placeholder: string | undefined,
  extensions: Extension[],
): Extension[] {
  const result: Extension[] = [updateListener];
  if (placeholder) {
    result.push(placeholderExtension(placeholder));
  }
  result.push(...extensions);
  return result;
}

/** Create and mount a new EditorView on the given container */
function createEditorView(
  container: HTMLDivElement,
  doc: string,
  allExtensions: Extension[],
): EditorView {
  const state = EditorState.create({ doc, extensions: allExtensions });
  return new EditorView({ state, parent: container });
}

export function useCodeMirror({
  value,
  onChange,
  extensions = [],
  placeholder,
}: UseCodeMirrorOptions): { containerRef: RefObject<HTMLDivElement | null> } {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  const initialValueRef = useRef(value);

  // Keep onChange ref updated without causing re-renders
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  // Create editor only once on mount (or when extensions/placeholder change)
  useEffect(() => {
    if (!containerRef.current) {
      return;
    }

    const updateListener = EditorView.updateListener.of((update: ViewUpdate) => {
      if (update.docChanged && onChangeRef.current) {
        onChangeRef.current(update.state.doc.toString());
      }
    });

    const allExtensions = buildExtensions(updateListener, placeholder, extensions);
    const view = createEditorView(containerRef.current, initialValueRef.current, allExtensions);
    viewRef.current = view;

    return (): void => {
      view.destroy();
      viewRef.current = null;
    };
  }, [placeholder, extensions]);

  // Sync external value changes to editor (e.g., undo/redo, reset)
  useEffect(() => {
    if (viewRef.current && value !== viewRef.current.state.doc.toString()) {
      const transaction = viewRef.current.state.update({
        changes: {
          from: 0,
          to: viewRef.current.state.doc.length,
          insert: value,
        },
      });
      viewRef.current.dispatch(transaction);
    }
  }, [value]);

  return { containerRef };
}
