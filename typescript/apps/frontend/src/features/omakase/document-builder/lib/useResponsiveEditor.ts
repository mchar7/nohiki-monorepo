import { useEffect, useState } from 'react';
import type { TemplateResponse } from '@/shared/api';
import { BREAKPOINTS } from '@/shared/lib/index.ts';
import { useDragResize } from './useDragResize.ts';

const EDITOR_FONT_SIZE: number = 14;
const EDITOR_TAB_SIZE: number = 2;

/** Static editor configuration - never changes between renders. */
const EDITOR_CONFIG = {
  theme: 'vs-dark',
  language: 'html',
  automaticLayout: true,
  minimap: { enabled: false },
  scrollBeyondLastLine: false,
  wordWrap: 'on' as const,
  lineNumbers: 'on' as const,
  fontSize: EDITOR_FONT_SIZE,
  tabSize: EDITOR_TAB_SIZE,
} as const;

/** Tracks whether the viewport is wide enough for the side-by-side editor layout. */
function useWindowResize(): {
  isEditorVisible: boolean;
  toggleEditor: () => void;
} {
  const [isEditorVisible, setIsEditorVisible] = useState(true);

  useEffect(() => {
    const handleResize = (): void => {
      setIsEditorVisible(window.innerWidth >= BREAKPOINTS.md);
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const toggleEditor = () => setIsEditorVisible((prev) => !prev);
  return { isEditorVisible, toggleEditor };
}

interface DialogPreviewState {
  showMobilePreview: boolean;
  setShowMobilePreview: (value: boolean) => void;
  dialogHtmlData: string | null;
  setDialogHtmlData: (value: string | null) => void;
  isGeneratingForDialog: boolean;
  generatePreviewForDialog: () => void;
}

/** Manages dialog-based preview state for fullscreen preview generation. */
function useDialogPreview(templateId: string | undefined): DialogPreviewState {
  const [showMobilePreview, setShowMobilePreview] = useState(false);
  const [dialogHtmlData, setDialogHtmlData] = useState<string | null>(null);
  const [isGeneratingForDialog, setIsGeneratingForDialog] = useState(false);

  const generatePreviewForDialog = () => {
    if (!templateId) {
      return;
    }
    setIsGeneratingForDialog(true);
    setShowMobilePreview(true);
    // Actual generation happens in FullscreenPreviewDialog; this opens the dialog
    setIsGeneratingForDialog(false);
  };

  return {
    showMobilePreview,
    setShowMobilePreview,
    dialogHtmlData,
    setDialogHtmlData,
    isGeneratingForDialog,
    generatePreviewForDialog,
  };
}

interface UseResponsiveEditorProps {
  template?: TemplateResponse | undefined;
  disabled?: boolean;
}

interface ResponsiveEditorResult {
  isEditorVisible: boolean;
  editorWidth: string;
  previewWidth: string;
  isDragging: boolean;
  schema: Record<string, unknown> | null;
  showMobilePreview: boolean;
  setShowMobilePreview: (value: boolean) => void;
  dialogHtmlData: string | null;
  setDialogHtmlData: (value: string | null) => void;
  isGeneratingForDialog: boolean;
  generatePreviewForDialog: () => void;
  containerRef: React.RefObject<HTMLDivElement | null>;
  toggleEditor: () => void;
  resetLayout: () => void;
  startDrag: (e: React.MouseEvent) => void;
  startTouchDrag: (e: React.TouchEvent) => void;
  editorConfig: typeof EDITOR_CONFIG;
  disabled: boolean;
}

export function useResponsiveEditor({
  template,
  disabled = false,
}: UseResponsiveEditorProps): ResponsiveEditorResult {
  const [schema, setSchema] = useState<Record<string, unknown> | null>(null);

  const drag = useDragResize();
  const { isEditorVisible, toggleEditor } = useWindowResize();
  const dialog = useDialogPreview(template?.id);

  useEffect(() => {
    setSchema((template?.content_schema as Record<string, unknown> | null | undefined) ?? null);
  }, [template?.content_schema]);

  return {
    isEditorVisible,
    editorWidth: drag.editorWidth,
    previewWidth: drag.previewWidth,
    isDragging: drag.isDragging,
    schema,
    showMobilePreview: dialog.showMobilePreview,
    setShowMobilePreview: dialog.setShowMobilePreview,
    dialogHtmlData: dialog.dialogHtmlData,
    setDialogHtmlData: dialog.setDialogHtmlData,
    isGeneratingForDialog: dialog.isGeneratingForDialog,
    generatePreviewForDialog: dialog.generatePreviewForDialog,
    containerRef: drag.containerRef,
    toggleEditor,
    resetLayout: drag.resetLayout,
    startDrag: drag.startDrag,
    startTouchDrag: drag.startTouchDrag,
    editorConfig: EDITOR_CONFIG,
    disabled,
  };
}
