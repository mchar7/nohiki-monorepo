/**
 * CSRF (Cross-Site Request Forgery) protection utilities.
 *
 * These utilities help generate and validate CSRF tokens for
 * state-changing requests. The tokens should be:
 * - Generated once per session
 * - Included in request headers for POST/PUT/DELETE/PATCH
 * - Validated by the backend
 */

/** CSRF token storage key */
const CSRF_TOKEN_KEY = 'nohiki-csrf-token';

const MS_PER_SECOND: number = 1000;
const SECONDS_PER_MINUTE: number = 60;
const MINUTES_PER_HOUR: number = 60;
const HOURS_PER_DAY: number = 24;
/** Token expiration time (24 hours) */
const TOKEN_EXPIRY_MS: number =
  HOURS_PER_DAY * MINUTES_PER_HOUR * SECONDS_PER_MINUTE * MS_PER_SECOND;

/** Default nonce length in bytes */
const DEFAULT_NONCE_LENGTH: number = 32;
/** Hex padding width per byte (2 hex chars per byte) */
const HEX_CHARS_PER_BYTE: number = 2;
/** Radix for hexadecimal number base */
const HEX_RADIX: number = 16;

/** Stored token metadata */
interface TokenMetadata {
  readonly token: string;
  readonly createdAt: number;
}

/**
 * Generates a cryptographically secure random string.
 *
 */
function generateNonce(length: number = DEFAULT_NONCE_LENGTH): string {
  const array = new Uint8Array(length);
  crypto.getRandomValues(array);
  return Array.from(array, (byte) =>
    byte.toString(HEX_RADIX).padStart(HEX_CHARS_PER_BYTE, '0'),
  ).join('');
}

/**
 * Generates a new CSRF token and stores it in session storage.
 * If a valid token already exists, returns the existing token.
 *
 */
function generateCSRFToken(): string {
  try {
    // Check for existing valid token
    const stored = globalThis.sessionStorage?.getItem(CSRF_TOKEN_KEY);
    if (stored) {
      const metadata = JSON.parse(stored) as TokenMetadata;
      const age = Date.now() - metadata.createdAt;

      if (age < TOKEN_EXPIRY_MS) {
        return metadata.token;
      }
    }

    // Generate new token
    const token = generateNonce(DEFAULT_NONCE_LENGTH);
    const metadata: TokenMetadata = {
      token,
      createdAt: Date.now(),
    };

    globalThis.sessionStorage?.setItem(CSRF_TOKEN_KEY, JSON.stringify(metadata));
    return token;
  } catch {
    // If storage is unavailable, generate a memory-only token
    return generateNonce(DEFAULT_NONCE_LENGTH);
  }
}

/**
 * Validates a CSRF token against the stored token.
 *
 */
function validateCSRFToken(token: string): boolean {
  if (!token) {
    return false;
  }

  try {
    const stored = globalThis.sessionStorage?.getItem(CSRF_TOKEN_KEY);
    if (!stored) {
      return false;
    }

    const metadata = JSON.parse(stored) as TokenMetadata;

    // Check expiration
    const age = Date.now() - metadata.createdAt;
    if (age >= TOKEN_EXPIRY_MS) {
      globalThis.sessionStorage?.removeItem(CSRF_TOKEN_KEY);
      return false;
    }

    // Constant-time comparison to prevent timing attacks
    return timingSafeEqual(token, metadata.token);
  } catch {
    return false;
  }
}

/**
 * Performs a constant-time string comparison to prevent timing attacks.
 *
 */
function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) {
    return false;
  }

  let result = 0;
  for (let i = 0; i < a.length; i += 1) {
    // biome-ignore lint/suspicious/noBitwiseOperators: intentional constant-time XOR comparison to prevent timing attacks
    result |= (a.codePointAt(i) ?? 0) ^ (b.codePointAt(i) ?? 0);
  }
  return result === 0;
}

export { generateCSRFToken, generateNonce, validateCSRFToken };
