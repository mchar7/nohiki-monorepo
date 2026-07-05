import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { LogLevel, logApiError, logComponentError, logger, logValidationError } from './logger.ts';

/** Expected numeric values for each LogLevel enum member */
const LOG_LEVEL_DEBUG: number = 0;
const LOG_LEVEL_INFO: number = 1;
const LOG_LEVEL_WARN: number = 2;
const LOG_LEVEL_ERROR: number = 3;

beforeEach(() => {
  vi.spyOn(console, 'debug').mockImplementation(() => {
    /* suppress test output */
  });
  vi.spyOn(console, 'info').mockImplementation(() => {
    /* suppress test output */
  });
  vi.spyOn(console, 'warn').mockImplementation(() => {
    /* suppress test output */
  });
  vi.spyOn(console, 'error').mockImplementation(() => {
    /* suppress test output */
  });
  vi.spyOn(console, 'log').mockImplementation(() => {
    /* suppress test output */
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('LogLevel enum', () => {
  test('has correct values', () => {
    expect(LogLevel.DEBUG).toBe(LOG_LEVEL_DEBUG);
    expect(LogLevel.INFO).toBe(LOG_LEVEL_INFO);
    expect(LogLevel.WARN).toBe(LOG_LEVEL_WARN);
    expect(LogLevel.ERROR).toBe(LOG_LEVEL_ERROR);
  });
});

describe('logger instance - debug and info', () => {
  test('logs debug messages', () => {
    logger.debug('Debug message');
    expect(console.debug).toHaveBeenCalled();
  });

  test('logs debug messages with context', () => {
    logger.debug('Debug message', { component: 'TestComponent', action: 'test' });
    expect(console.debug).toHaveBeenCalled();
  });

  test('logs info messages', () => {
    logger.info('Info message');
    expect(console.info).toHaveBeenCalled();
  });

  test('logs info messages with context', () => {
    logger.info('Info message', { userId: '123' });
    expect(console.info).toHaveBeenCalled();
  });
});

describe('logger instance - warn and error', () => {
  test('logs warn messages', () => {
    logger.warn('Warning message');
    expect(console.warn).toHaveBeenCalled();
  });

  test('logs warn messages with context', () => {
    logger.warn('Warning message', { component: 'WarningComponent' });
    expect(console.warn).toHaveBeenCalled();
  });

  test('logs error messages', () => {
    logger.error('Error message');
    expect(console.error).toHaveBeenCalled();
  });

  test('logs error messages with Error object', () => {
    const error = new Error('Test error');
    logger.error('Error occurred', error);
    expect(console.error).toHaveBeenCalled();
  });

  test('logs error messages with non-Error object', () => {
    logger.error('Error occurred', { code: 500 });
    expect(console.error).toHaveBeenCalled();
  });

  test('logs error messages with context', () => {
    const error = new Error('Test error');
    logger.error('Error occurred', error, { component: 'ErrorComponent' });
    expect(console.error).toHaveBeenCalled();
  });
});

describe('logApiError', () => {
  test('logs API errors with operation name', () => {
    const error = new Error('API failed');
    logApiError('fetchUsers', error);
    expect(console.error).toHaveBeenCalled();
  });

  test('logs API errors with additional context', () => {
    logApiError('fetchUsers', new Error('API failed'), { userId: '123' });
    expect(console.error).toHaveBeenCalled();
  });
});

describe('logComponentError', () => {
  test('logs component errors with component name', () => {
    const error = new Error('Component failed');
    logComponentError('UserList', error);
    expect(console.error).toHaveBeenCalled();
  });

  test('logs component errors with additional context', () => {
    logComponentError('UserList', new Error('Render failed'), { action: 'render' });
    expect(console.error).toHaveBeenCalled();
  });
});

describe('logValidationError', () => {
  test('logs validation errors with field name', () => {
    const error = new Error('Invalid email');
    logValidationError('email', error);
    expect(console.error).toHaveBeenCalled();
  });

  test('logs validation errors with additional context', () => {
    logValidationError('password', new Error('Too short'), { minLength: 8 });
    expect(console.error).toHaveBeenCalled();
  });
});
