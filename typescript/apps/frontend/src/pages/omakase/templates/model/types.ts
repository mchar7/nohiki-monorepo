// --- Page size ---

export interface PageSize {
  width: number;
  height: number;
  unit: 'mm' | 'in';
}

// --- Template ---

export type TemplateData = Record<string, unknown>;

export interface OmakaseTemplateMetadata {
  id: string;
  name: string;
  description: string;
  version: string;
  engine: string;
  pageSize: PageSize;
}

export type ValidationLevelType = 'error' | 'warning' | 'info';

export interface ExtendedValidationIssue {
  path: string;
  keyword: string;
  message: string;
  level: ValidationLevelType;
  line: number | null;
  column: number | null;
}

// --- Preview ---

export interface ScaleState {
  mode: 'fit' | 'actual' | 'custom';
  percentage: number;
  imageNaturalSize: { width: number; height: number } | null;
  containerSize: { width: number; height: number };
}

export interface PreviewState {
  imageUrl: string | null;
  imageNaturalSize: { width: number; height: number } | null;
  isGenerating: boolean;
  generationError: string | null;
  lastGeneratedAt: Date | null;
  scale: ScaleState;
  containerSize: { width: number; height: number };
  pageSize: PageSize;
  templateData: TemplateData | undefined;
}

export interface PreviewConfig {
  maxDimension: number;
  defaultQuality: number;
  scaleStep: number;
  minScale: number;
  maxScale: number;
  debounceMs: number;
  cacheSize: number;
}

export type EditorMode = 'simple' | 'advanced';

export interface TemplateStudioState {
  templateContent: string;
  templateMetadata: OmakaseTemplateMetadata;
  validationIssues: readonly ExtendedValidationIssue[];
  isValidating: boolean;
  errorCount: number;
  warningCount: number;
  validateTemplate: () => void;
  handleMetadataChange: (metadata: OmakaseTemplateMetadata) => void;
  handlePageSizeChange: (pageSize: PageSize) => void;
  handleTemplateChange: (content: string) => void;
  isSinglePane: boolean;
  settingsOpen: boolean;
  setSettingsOpen: (open: boolean) => void;
  previewOpen: boolean;
  handleTogglePreview: () => void;
  mobilePreviewOpen: boolean;
  setMobilePreviewOpen: (open: boolean) => void;
  isBackendAvailable: boolean;
  editorMode: EditorMode;
  setEditorMode: (mode: EditorMode) => void;
  templateData: TemplateData;
  handleTemplateDataChange: (data: TemplateData) => void;
  contentSchema: unknown;
}

export const DEFAULT_PREVIEW_CONFIG: PreviewConfig = {
  maxDimension: 4096,
  defaultQuality: 90,
  scaleStep: 25,
  minScale: 25,
  maxScale: 400,
  debounceMs: 300,
  cacheSize: 10,
};
