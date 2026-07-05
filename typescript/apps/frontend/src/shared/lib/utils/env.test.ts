import { describe, expect } from 'vitest';
import { env, isDevelopment, isProduction, isTest } from './env.ts';

describe('env', () => {
  describe('environment flags', () => {
    test('exports isDevelopment flag', () => {
      expect(typeof isDevelopment).toBe('boolean');
    });

    test('exports isProduction flag', () => {
      expect(typeof isProduction).toBe('boolean');
    });

    test('exports isTest flag', () => {
      expect(typeof isTest).toBe('boolean');
    });

    test('isTest is true in test environment', () => {
      expect(isTest).toBe(true);
    });
  });

  describe('env object', () => {
    test('has MODE property', () => {
      expect(env.MODE).toBe('test');
    });

    test('has DEV property', () => {
      expect(typeof env.DEV).toBe('boolean');
    });

    test('has PROD property', () => {
      expect(typeof env.PROD).toBe('boolean');
    });

    test('has VITE_API_BASE_URL with default', () => {
      expect(env.VITE_API_BASE_URL).toBeDefined();
      expect(typeof env.VITE_API_BASE_URL).toBe('string');
    });

    test('has VITE_APP_VERSION with default', () => {
      expect(env.VITE_APP_VERSION).toBeDefined();
      expect(typeof env.VITE_APP_VERSION).toBe('string');
    });
  });
});
