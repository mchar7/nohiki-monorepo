import { describe, expect } from 'vitest';
import { CACHE_CONFIG, STORAGE_KEYS } from './config.ts';

const MS_PER_SECOND: number = 1000;
const SECONDS_PER_MINUTE: number = 60;
const MS_PER_MINUTE: number = SECONDS_PER_MINUTE * MS_PER_SECOND;

const SESSION_STALE_MINUTES: number = 5;
const SESSION_GC_MINUTES: number = 30;
const USER_DATA_STALE_MINUTES: number = 2;
const USER_DATA_GC_MINUTES: number = 10;
const DYNAMIC_STALE_SECONDS: number = 30;
const DYNAMIC_GC_MINUTES: number = 5;
const STATIC_STALE_MINUTES: number = 10;
const STATIC_GC_MINUTES: number = 60;

describe('API config', () => {
  describe('CACHE_CONFIG', () => {
    test('has SESSION config with correct structure', () => {
      expect(CACHE_CONFIG.SESSION).toHaveProperty('staleTime');
      expect(CACHE_CONFIG.SESSION).toHaveProperty('gcTime');
      expect(CACHE_CONFIG.SESSION.staleTime).toBe(SESSION_STALE_MINUTES * MS_PER_MINUTE);
      expect(CACHE_CONFIG.SESSION.gcTime).toBe(SESSION_GC_MINUTES * MS_PER_MINUTE);
    });

    test('has USER_DATA config with correct structure', () => {
      expect(CACHE_CONFIG.USER_DATA).toHaveProperty('staleTime');
      expect(CACHE_CONFIG.USER_DATA).toHaveProperty('gcTime');
      expect(CACHE_CONFIG.USER_DATA.staleTime).toBe(USER_DATA_STALE_MINUTES * MS_PER_MINUTE);
      expect(CACHE_CONFIG.USER_DATA.gcTime).toBe(USER_DATA_GC_MINUTES * MS_PER_MINUTE);
    });

    test('has DYNAMIC config with correct structure', () => {
      expect(CACHE_CONFIG.DYNAMIC).toHaveProperty('staleTime');
      expect(CACHE_CONFIG.DYNAMIC).toHaveProperty('gcTime');
      expect(CACHE_CONFIG.DYNAMIC.staleTime).toBe(DYNAMIC_STALE_SECONDS * MS_PER_SECOND);
      expect(CACHE_CONFIG.DYNAMIC.gcTime).toBe(DYNAMIC_GC_MINUTES * MS_PER_MINUTE);
    });

    test('has STATIC config with correct structure', () => {
      expect(CACHE_CONFIG.STATIC).toHaveProperty('staleTime');
      expect(CACHE_CONFIG.STATIC).toHaveProperty('gcTime');
      expect(CACHE_CONFIG.STATIC.staleTime).toBe(STATIC_STALE_MINUTES * MS_PER_MINUTE);
      expect(CACHE_CONFIG.STATIC.gcTime).toBe(STATIC_GC_MINUTES * MS_PER_MINUTE);
    });

    test('has NONE config with zero values', () => {
      expect(CACHE_CONFIG.NONE.staleTime).toBe(0);
      expect(CACHE_CONFIG.NONE.gcTime).toBe(0);
    });
  });

  describe('STORAGE_KEYS', () => {
    test('has all expected keys', () => {
      expect(STORAGE_KEYS).toHaveProperty('AUTH_STATE');
      expect(STORAGE_KEYS).toHaveProperty('SELECTED_PROFILE');
      expect(STORAGE_KEYS).toHaveProperty('THEME');
      expect(STORAGE_KEYS).toHaveProperty('SIDEBAR_COLLAPSED');
    });

    test('has correct key values', () => {
      expect(STORAGE_KEYS.AUTH_STATE).toBe('nohiki:auth:state');
      expect(STORAGE_KEYS.SELECTED_PROFILE).toBe('nohiki:profile:selected');
      expect(STORAGE_KEYS.THEME).toBe('nohiki:theme');
      expect(STORAGE_KEYS.SIDEBAR_COLLAPSED).toBe('nohiki:sidebar:collapsed');
    });
  });
});
