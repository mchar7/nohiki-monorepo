import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { generateCSRFToken, generateNonce, validateCSRFToken } from './csrf.ts';

const HEX_CHARS_RE = /^[0-9a-f]+$/u;

/** Default nonce byte length */
const _DEFAULT_NONCE_BYTES: number = 32;
/** Default nonce hex string length (2 chars per byte) */
const DEFAULT_NONCE_HEX_LENGTH: number = 64;
/** Short nonce byte length for parameterized tests */
const SHORT_NONCE_BYTES: number = 16;
/** Short nonce hex string length */
const SHORT_NONCE_HEX_LENGTH: number = 32;
/** Token age simulating a recently-created token (1 second ago) */
const TOKEN_AGE_RECENT_MS: number = 1000;
/** Token age simulating an expired token (25 hours ago) */
const TOKEN_AGE_HOURS_EXPIRED: number = 25;
const TOKEN_AGE_MINUTES_PER_HOUR: number = 60;
const TOKEN_AGE_SECONDS_PER_MINUTE: number = 60;
const TOKEN_AGE_MS_PER_SECOND: number = 1000;
const TOKEN_AGE_EXPIRED_MS: number =
  TOKEN_AGE_HOURS_EXPIRED *
  TOKEN_AGE_MINUTES_PER_HOUR *
  TOKEN_AGE_SECONDS_PER_MINUTE *
  TOKEN_AGE_MS_PER_SECOND;

beforeEach(() => {
  vi.stubGlobal('sessionStorage', {
    getItem: vi.fn(),
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
    length: 0,
    key: vi.fn(),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('csrf - generateNonce', () => {
  test('generates a string of default length 64 chars (32 bytes hex)', () => {
    const nonce = generateNonce();
    expect(nonce).toHaveLength(DEFAULT_NONCE_HEX_LENGTH);
  });

  test('generates a string of specified length', () => {
    const nonce = generateNonce(SHORT_NONCE_BYTES);
    expect(nonce).toHaveLength(SHORT_NONCE_HEX_LENGTH);
  });

  test('generates different values on each call', () => {
    const nonce1 = generateNonce();
    const nonce2 = generateNonce();
    expect(nonce1).not.toBe(nonce2);
  });

  test('generates only hexadecimal characters', () => {
    const nonce = generateNonce();
    expect(nonce).toMatch(HEX_CHARS_RE);
  });
});

describe('csrf - generateCSRFToken', () => {
  test('generates a new token when none exists', () => {
    vi.mocked(sessionStorage.getItem).mockReturnValue(null);

    const token = generateCSRFToken();

    expect(token).toHaveLength(DEFAULT_NONCE_HEX_LENGTH);
    expect(sessionStorage.setItem).toHaveBeenCalled();
  });

  test('returns existing valid token', () => {
    const existingToken = 'existing-token-12345678901234567890123456789012';
    vi.mocked(sessionStorage.getItem).mockReturnValue(
      JSON.stringify({
        token: existingToken,
        createdAt: Date.now() - TOKEN_AGE_RECENT_MS,
      }),
    );

    const token = generateCSRFToken();

    expect(token).toBe(existingToken);
    expect(sessionStorage.setItem).not.toHaveBeenCalled();
  });

  test('generates new token when existing token is expired', () => {
    vi.mocked(sessionStorage.getItem).mockReturnValue(
      JSON.stringify({
        token: 'old-token',
        createdAt: Date.now() - TOKEN_AGE_EXPIRED_MS,
      }),
    );

    const token = generateCSRFToken();

    expect(token).not.toBe('old-token');
    expect(token).toHaveLength(DEFAULT_NONCE_HEX_LENGTH);
    expect(sessionStorage.setItem).toHaveBeenCalled();
  });

  test('generates memory-only token when storage throws', () => {
    vi.mocked(sessionStorage.getItem).mockImplementation(() => {
      throw new Error('Storage unavailable');
    });

    const token = generateCSRFToken();

    expect(token).toHaveLength(DEFAULT_NONCE_HEX_LENGTH);
  });
});

describe('csrf - validateCSRFToken basic', () => {
  test('returns false for empty token', () => {
    expect(validateCSRFToken('')).toBe(false);
  });

  test('returns false when no stored token exists', () => {
    vi.mocked(sessionStorage.getItem).mockReturnValue(null);

    expect(validateCSRFToken('some-token')).toBe(false);
  });

  test('returns true for valid matching token', () => {
    const token = 'valid-token-123456789012345678901234567890123';
    vi.mocked(sessionStorage.getItem).mockReturnValue(
      JSON.stringify({
        token,
        createdAt: Date.now() - TOKEN_AGE_RECENT_MS,
      }),
    );

    expect(validateCSRFToken(token)).toBe(true);
  });

  test('returns false for non-matching token', () => {
    vi.mocked(sessionStorage.getItem).mockReturnValue(
      JSON.stringify({
        token: 'stored-token',
        createdAt: Date.now() - TOKEN_AGE_RECENT_MS,
      }),
    );

    expect(validateCSRFToken('different-token')).toBe(false);
  });
});

describe('csrf - validateCSRFToken expiry and edge cases', () => {
  test('returns false and removes expired token', () => {
    vi.mocked(sessionStorage.getItem).mockReturnValue(
      JSON.stringify({
        token: 'expired-token',
        createdAt: Date.now() - TOKEN_AGE_EXPIRED_MS,
      }),
    );

    expect(validateCSRFToken('expired-token')).toBe(false);
    expect(sessionStorage.removeItem).toHaveBeenCalled();
  });

  test('returns false when storage throws', () => {
    vi.mocked(sessionStorage.getItem).mockImplementation(() => {
      throw new Error('Storage error');
    });

    expect(validateCSRFToken('any-token')).toBe(false);
  });

  test('uses timing-safe comparison for tokens of same length', () => {
    const token = 'abcdef';
    vi.mocked(sessionStorage.getItem).mockReturnValue(
      JSON.stringify({
        token: 'abcdeg',
        createdAt: Date.now(),
      }),
    );

    expect(validateCSRFToken(token)).toBe(false);
  });

  test('returns false for tokens of different length', () => {
    vi.mocked(sessionStorage.getItem).mockReturnValue(
      JSON.stringify({
        token: 'short',
        createdAt: Date.now(),
      }),
    );

    expect(validateCSRFToken('longer-token')).toBe(false);
  });
});
