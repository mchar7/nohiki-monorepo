/**
 * Centralized error messages for the Nohiki frontend.
 *
 * These constants provide:
 * 1. Type-safe error message access
 * 2. Consistent wording across components
 * 3. Single source of truth for user-facing messages
 * 4. i18n support
 *
 * Usage:
 *   import { ErrorMessages } from '@/shared/lib/errors';
 *   toast.error(ErrorMessages.AUTH.INVALID_CREDENTIALS);
 */

export const ErrorMessages = {
  AUTH: {
    INVALID_CREDENTIALS: 'Invalid email or password',
    SESSION_EXPIRED: 'Your session has expired. Please login again.',
    UNAUTHORIZED: 'You must be logged in to perform this action',
    EMAIL_IN_USE: 'An account with this email already exists',
    WEAK_PASSWORD: 'Password must be at least 8 characters with uppercase, lowercase, and number',
    REGISTRATION_FAILED: 'Registration failed. Please try again.',
    LOGOUT_FAILED: 'Failed to logout. Please try again.',
  },

  PROFILE: {
    NOT_FOUND: 'Profile not found',
    DUPLICATE_NAME: 'A profile with this name already exists',
    CREATE_FAILED: 'Failed to create profile. Please try again.',
    UPDATE_FAILED: 'Failed to update profile. Please try again.',
    DELETE_FAILED: 'Failed to delete profile. Please try again.',
    FETCH_FAILED: 'Failed to load profiles. Please try again.',
    MAX_PROFILES_REACHED: 'You have reached the maximum number of profiles',
  },

  ATTACHMENT: {
    NOT_FOUND: 'Attachment not found',
    UPLOAD_FAILED: 'File upload failed. Please try again.',
    DELETE_FAILED: 'Failed to delete attachment. Please try again.',
    FILE_TOO_LARGE: 'File size exceeds the maximum limit of 10MB',
    INVALID_TYPE: 'Invalid file type. Please upload a PDF, DOC, or DOCX file.',
  },

  LISTING: {
    NOT_FOUND: 'Job listing not found',
    FETCH_FAILED: 'Failed to load job listings. Please try again.',
  },

  CORRELATION: {
    NOT_FOUND: 'Match not found',
    FETCH_FAILED: 'Failed to load matches. Please try again.',
    FEEDBACK_FAILED: 'Failed to submit feedback. Please try again.',
  },

  DOCUMENT: {
    GENERATION_FAILED: 'Document generation failed. Please try again.',
    TEMPLATE_NOT_FOUND: 'Template not found',
    SCHEMA_INVALID: 'Invalid document schema',
    FETCH_FAILED: 'Failed to load documents. Please try again.',
  },

  NETWORK: {
    CONNECTION_FAILED: 'Unable to connect to server. Please check your connection.',
    TIMEOUT: 'Request timed out. Please try again.',
    SERVER_ERROR: 'Server error. Please try again later.',
  },

  VALIDATION: {
    REQUIRED_FIELD: (field: string) => `${field} is required`,
    INVALID_EMAIL: 'Please enter a valid email address',
    INVALID_URL: 'Please enter a valid URL',
    MIN_LENGTH: (field: string, min: number) => `${field} must be at least ${min} characters`,
    MAX_LENGTH: (field: string, max: number) => `${field} must be at most ${max} characters`,
  },
} as const;

/**
 * Error code to message mapping for API responses.
 *
 * Backend returns error_code (e.g., "AUTH.INVALID_CREDENTIALS"),
 * frontend maps to user-friendly message.
 */
export const ErrorCodeMap: Record<string, string> = {
  'AUTH.INVALID_CREDENTIALS': ErrorMessages.AUTH.INVALID_CREDENTIALS,
  'AUTH.SESSION_EXPIRED': ErrorMessages.AUTH.SESSION_EXPIRED,
  'AUTH.UNAUTHORIZED': ErrorMessages.AUTH.UNAUTHORIZED,
  'AUTH.EMAIL_IN_USE': ErrorMessages.AUTH.EMAIL_IN_USE,
  'PROFILE.NOT_FOUND': ErrorMessages.PROFILE.NOT_FOUND,
  'PROFILE.DUPLICATE_NAME': ErrorMessages.PROFILE.DUPLICATE_NAME,
  'PROFILE.MAX_PROFILES_REACHED': ErrorMessages.PROFILE.MAX_PROFILES_REACHED,
  'ATTACHMENT.NOT_FOUND': ErrorMessages.ATTACHMENT.NOT_FOUND,
  'ATTACHMENT.FILE_TOO_LARGE': ErrorMessages.ATTACHMENT.FILE_TOO_LARGE,
  'ATTACHMENT.INVALID_TYPE': ErrorMessages.ATTACHMENT.INVALID_TYPE,
  'LISTING.NOT_FOUND': ErrorMessages.LISTING.NOT_FOUND,
  'CORRELATION.NOT_FOUND': ErrorMessages.CORRELATION.NOT_FOUND,
  'DOCUMENT.TEMPLATE_NOT_FOUND': ErrorMessages.DOCUMENT.TEMPLATE_NOT_FOUND,
  'DOCUMENT.GENERATION_FAILED': ErrorMessages.DOCUMENT.GENERATION_FAILED,
  'VALIDATION.ERROR': 'Please check your input and try again.',
  'NETWORK.SERVER_ERROR': ErrorMessages.NETWORK.SERVER_ERROR,
};

/**
 * Get user-friendly message from API error code.
 */
export function getErrorMessage(errorCode: string): string {
  return ErrorCodeMap[errorCode] ?? ErrorMessages.NETWORK.SERVER_ERROR;
}

/**
 * Extracts a human-readable reason string from an API error.
 *
 * Handles common error shapes from @hey-api and fetch errors:
 * - `{ detail: string }` - FastAPI validation/HTTPException
 * - `{ message: string }` - Standard Error objects
 * - `{ error_code: string }` - Backend typed error codes
 * - Plain string errors
 *
 * Returns `undefined` if no meaningful reason can be extracted,
 * allowing callers to fall back to a generic message.
 */
export function extractErrorReason(error: unknown): string | undefined {
  if (typeof error === 'string') {
    return error;
  }
  if (!(typeof error === 'object' && error !== null)) {
    return;
  }

  const err = error as Record<string, unknown>;

  // FastAPI detail field (HTTPException, RequestValidationError)
  if (typeof err.detail === 'string') {
    return err.detail;
  }

  // Backend typed error codes
  if (typeof err.error_code === 'string') {
    return ErrorCodeMap[err.error_code] ?? String(err.error_code);
  }

  // Standard Error.message
  if (typeof err.message === 'string' && err.message.length > 0) {
    return err.message;
  }
}
