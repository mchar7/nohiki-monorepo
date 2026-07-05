import {
  autocompletion,
  closeBrackets,
  closeBracketsKeymap,
  completionKeymap,
} from '@codemirror/autocomplete';
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { html } from '@codemirror/lang-html';
import {
  bracketMatching,
  defaultHighlightStyle,
  foldGutter,
  foldKeymap,
  indentOnInput,
  syntaxHighlighting,
} from '@codemirror/language';
import { lintKeymap } from '@codemirror/lint';
import { highlightSelectionMatches, searchKeymap } from '@codemirror/search';
import type { Extension } from '@codemirror/state';
import { EditorState } from '@codemirror/state';
import { oneDark } from '@codemirror/theme-one-dark';
import {
  crosshairCursor,
  drawSelection,
  dropCursor,
  highlightActiveLineGutter,
  highlightSpecialChars,
  keymap,
  lineNumbers,
  rectangularSelection,
} from '@codemirror/view';
import type { JSX } from 'react';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useTheme } from '@/shared/lib/index.ts';
import { useCodeMirror } from '../lib/useCodeMirror.ts';

interface CodeMirrorEditorProps {
  /** Current editor value */
  readonly value: string;
  /** Callback when value changes */
  readonly onChange?: (value: string) => void;
  /** Additional CSS classes */
  readonly className?: string;
  /** Placeholder text when editor is empty */
  readonly placeholder?: string;
}

/**
 * CodeMirror-based HTML template editor.
 * The parent component (EditorPanel) provides the header with validation info.
 */
export function CodeMirrorEditor({
  value,
  onChange,
  className = '',
  placeholder,
}: CodeMirrorEditorProps): JSX.Element {
  const { t } = useTranslation('omakase.templateStudio');
  const { theme } = useTheme();
  const isDark =
    theme === 'dark' ||
    (theme === 'system' && globalThis.matchMedia('(prefers-color-scheme: dark)').matches);

  const editorPlaceholder = placeholder ?? t('editor.placeholder');

  // Memoize extensions to prevent editor recreation on every render
  const extensions = useMemo<Extension[]>(() => {
    const baseExtensions: Extension[] = [
      lineNumbers(),
      highlightActiveLineGutter(),
      highlightSpecialChars(),
      history(),
      foldGutter(),
      drawSelection(),
      dropCursor(),
      EditorState.allowMultipleSelections.of(true),
      indentOnInput(),
      bracketMatching(),
      closeBrackets(),
      autocompletion(),
      rectangularSelection(),
      crosshairCursor(),
      highlightSelectionMatches(),
      syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      keymap.of([
        ...closeBracketsKeymap,
        ...defaultKeymap,
        ...searchKeymap,
        ...historyKeymap,
        ...foldKeymap,
        ...completionKeymap,
        ...lintKeymap,
      ]),
      html(),
    ];
    if (isDark) {
      baseExtensions.push(oneDark);
    }
    return baseExtensions;
  }, [isDark]);

  const { containerRef } = useCodeMirror({
    value,
    onChange,
    extensions,
    placeholder: editorPlaceholder,
  });

  return <div ref={containerRef} className={`h-full overflow-auto ${className}`} />;
}
