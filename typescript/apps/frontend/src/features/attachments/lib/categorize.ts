type DocumentCategory = 'resume' | 'cover_letter' | 'portfolio' | 'other';

const DOCUMENT_CATEGORIES = ['resume', 'cover_letter', 'portfolio', 'other'] as const;

const CATEGORY_PATTERNS: readonly {
  category: DocumentCategory;
  keywords: readonly string[];
}[] = [
  { category: 'resume', keywords: ['resume', 'cv', 'curriculum'] },
  { category: 'cover_letter', keywords: ['cover', 'coverletter', 'cover_letter', 'motivation'] },
  { category: 'portfolio', keywords: ['portfolio', 'folio', 'work_samples'] },
];

const STORAGE_KEY_PREFIX = 'attachment-category:';

const EXTENSION_PATTERN = /\.[^.]+$/u;
const NORMALIZE_PATTERN = /[^a-z0-9]/gu;

/**
 * Infers a document category from a filename using case-insensitive keyword matching.
 * Strips the file extension before matching against known patterns.
 */
function inferCategory(filename: string): DocumentCategory {
  const nameWithoutExtension = filename.replace(EXTENSION_PATTERN, '');
  const normalized = nameWithoutExtension.toLowerCase().replace(NORMALIZE_PATTERN, '_');

  for (const { category, keywords } of CATEGORY_PATTERNS) {
    if (keywords.some((keyword) => normalized.includes(keyword))) {
      return category;
    }
  }

  return 'other';
}

function getCategoryStorageKey(uploadId: string): string {
  return `${STORAGE_KEY_PREFIX}${uploadId}`;
}

function saveCategory(uploadId: string, category: DocumentCategory): void {
  localStorage.setItem(getCategoryStorageKey(uploadId), category);
}

function loadCategory(uploadId: string): DocumentCategory | null {
  const stored = localStorage.getItem(getCategoryStorageKey(uploadId));
  if (stored && DOCUMENT_CATEGORIES.includes(stored as DocumentCategory)) {
    return stored as DocumentCategory;
  }
  return null;
}

export type { DocumentCategory };
export { DOCUMENT_CATEGORIES, inferCategory, loadCategory, saveCategory };
