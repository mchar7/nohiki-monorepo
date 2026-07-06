type BadgeVariant = 'default' | 'destructive' | 'secondary' | 'outline';

interface StatusTheme {
  readonly className: string;
  readonly variant?: BadgeVariant;
  /** Show an animated spinner icon before the label. */
  readonly spinning?: boolean;
}

/**
 * Theme map for correlation statuses.
 * Keys match the CorrelationStatus enum values.
 */
const correlationStatusThemes: Record<string, StatusTheme> = {
  pending: {
    className: 'bg-blue-500/10 text-blue-700 dark:text-blue-400 border-blue-500/20',
    variant: 'outline',
  },
  evaluated: {
    className: 'bg-blue-500/10 text-blue-700 dark:text-blue-400 border-blue-500/20',
    variant: 'outline',
  },
  viewed: {
    className: 'bg-gray-500/10 text-gray-700 dark:text-gray-400 border-gray-500/20',
    variant: 'outline',
  },
  saved: {
    className: 'bg-purple-500/10 text-purple-700 dark:text-purple-400 border-purple-500/20',
    variant: 'outline',
  },
  applied: {
    className: 'bg-green-500/10 text-green-700 dark:text-green-400 border-green-500/20',
    variant: 'outline',
  },
  dismissed: {
    className: 'bg-red-500/10 text-red-700 dark:text-red-400 border-red-500/20',
    variant: 'outline',
  },
  expired: {
    className: 'bg-orange-500/10 text-orange-700 dark:text-orange-400 border-orange-500/20',
    variant: 'outline',
  },
};

/**
 * Theme map for document statuses.
 * Keys match the document status string values from the API.
 */
const documentStatusThemes: Record<string, StatusTheme> = {
  completed: { className: '', variant: 'default' },
  failed: { className: '', variant: 'destructive' },
  processing: { className: '', variant: 'secondary', spinning: true },
  pending: { className: '', variant: 'outline' },
};

const FALLBACK_STATUS_THEME: StatusTheme = { className: '', variant: 'outline' };

export type { StatusTheme };
export { correlationStatusThemes, documentStatusThemes, FALLBACK_STATUS_THEME };
