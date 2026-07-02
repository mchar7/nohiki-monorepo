import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { workerLogger } from './logger';

const ISO_TIMESTAMP_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/u;
const HTTP_INTERNAL_SERVER_ERROR = 500;
const LOGGER_CALL_COUNT = 3;

interface ParsedLogEntry {
  level: 'info' | 'warn' | 'error';
  message: string;
  timestamp: string;
  traceId?: string;
  spanId?: string;
  [key: string]: unknown;
}

function getLastLogEntry(spy: ReturnType<typeof vi.spyOn>): ParsedLogEntry {
  const { calls } = spy.mock;
  const last = calls.at(-1);
  if (!last || typeof last[0] !== 'string') {
    throw new Error('Expected console.log to be called with a JSON string');
  }
  return JSON.parse(last[0]) as ParsedLogEntry;
}

let consoleSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {
    // Suppress output while capturing calls.
  });
});

afterEach(() => {
  consoleSpy.mockRestore();
});

describe('workerLogger formatting', () => {
  it('emits a JSON string with level, message, and ISO timestamp on info', () => {
    workerLogger.info('request received');

    const entry = getLastLogEntry(consoleSpy);
    expect(entry.level).toBe('info');
    expect(entry.message).toBe('request received');
    expect(entry.timestamp).toMatch(ISO_TIMESTAMP_RE);
  });

  it('merges extra fields into the log entry', () => {
    workerLogger.info('cache hit', { country: 'USA', cache: 'hit' });

    const entry = getLastLogEntry(consoleSpy);
    expect(entry.country).toBe('USA');
    expect(entry.cache).toBe('hit');
  });

  it('omits traceId/spanId when no active span exists', () => {
    workerLogger.info('no span context');

    const entry = getLastLogEntry(consoleSpy);
    expect(entry.traceId).toBeUndefined();
    expect(entry.spanId).toBeUndefined();
  });

  it('emits valid JSON that round-trips through JSON.parse', () => {
    workerLogger.error('boom', {
      extra: { status: HTTP_INTERNAL_SERVER_ERROR, path: '/auth-listings' },
    });

    const raw = consoleSpy.mock.calls.at(-1)?.[0];
    expect(typeof raw).toBe('string');
    expect(() => JSON.parse(raw as string)).not.toThrow();
  });
});

describe('workerLogger severity methods', () => {
  it('uses level="warn" on warn()', () => {
    workerLogger.warn('BFF returned non-OK');

    expect(getLastLogEntry(consoleSpy).level).toBe('warn');
  });

  it('uses level="error" on error()', () => {
    workerLogger.error('fetch failed');

    expect(getLastLogEntry(consoleSpy).level).toBe('error');
  });
});

describe('workerLogger call count', () => {
  it('emits exactly one console.log call per logger method invocation', () => {
    workerLogger.info('first');
    workerLogger.warn('second');
    workerLogger.error('third');

    expect(consoleSpy).toHaveBeenCalledTimes(LOGGER_CALL_COUNT);
  });
});
