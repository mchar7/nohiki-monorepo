/**
 * Standardized toast message i18n keys.
 *
 * All messages use past-tense format for consistency:
 * "Profile updated", "Document deleted", "Password changed", etc.
 *
 * Usage:
 * ```tsx
 * import { TOAST_MESSAGES } from '@/shared/lib';
 * toast.success(t(TOAST_MESSAGES.PROFILE_UPDATED));
 * ```
 */

// ── Success messages (past-tense: entity + action) ──────────────────
export const TOAST_SUCCESS = {
  PROFILE_UPDATED: 'account:feedback.profileUpdated',
  PASSWORD_CHANGED: 'account:feedback.passwordChanged',
  ACCOUNT_DELETED: 'account:deleteAccount.success',
  FEEDBACK_SUBMITTED: 'jobs:feedback.feedbackSuccess',
  ATTACHMENT_DELETED: 'attachments:feedback.deleted',
  DATA_IMPORTED: 'dataManagement.importSuccess',
} as const;

// ── Error messages ──────────────────────────────────────────────────
export const TOAST_ERROR = {
  PROFILE_UPDATE_FAILED: 'account:feedback.updateError',
  PASSWORD_CHANGE_FAILED: 'account:feedback.passwordError',
  ACCOUNT_DELETE_FAILED: 'account:deleteAccount.error',
  GENERIC: 'common:errors.generic',
  NETWORK: 'common:errors.network',
  PROVIDER_UNAVAILABLE: 'auth:oauth.providerUnavailable',
} as const;
