import { describe, expect } from 'vitest';
import { nonNull } from '@/shared/test-utils';
import type { AuthListingItem, AuthListingsResponse } from './types';

/**
 * Compile-time type validation for auth-listings domain types.
 *
 * These tests verify the interface shapes at compile time (TypeScript will reject
 * invalid assignments) and at runtime confirm the objects satisfy structural expectations.
 */

describe('AuthListingItem', () => {
  test('accepts a fully populated item', () => {
    const item: AuthListingItem = {
      title: 'Software Engineer',
      company_name: 'Acme Corp',
      location_raw: 'Berlin, Germany',
      work_arrangement: 'Remote',
      required_skills: ['TypeScript', 'React'],
      posted_at: '2025-03-01T00:00:00Z',
      language: 'en',
    };

    expect(item.title).toBe('Software Engineer');
    expect(item.company_name).toBe('Acme Corp');
    expect(item.location_raw).toBe('Berlin, Germany');
    expect(item.work_arrangement).toBe('Remote');
    expect(item.required_skills).toEqual(['TypeScript', 'React']);
    expect(item.posted_at).toBe('2025-03-01T00:00:00Z');
    expect(item.language).toBe('en');
  });

  test('accepts null for optional fields', () => {
    const item: AuthListingItem = {
      title: 'Backend Developer',
      company_name: 'Startup Inc',
      location_raw: null,
      work_arrangement: null,
      required_skills: [],
      posted_at: '2025-06-15T12:00:00Z',
      language: null,
    };

    expect(item.location_raw).toBeNull();
    expect(item.work_arrangement).toBeNull();
    expect(item.language).toBeNull();
    expect(item.required_skills).toEqual([]);
  });
});

describe('AuthListingsResponse', () => {
  test('has listings array and country string', () => {
    const response: AuthListingsResponse = {
      listings: [],
      country: 'DEU',
    };

    expect(response.listings).toEqual([]);
    expect(response.country).toBe('DEU');
  });

  test('holds multiple listing items', () => {
    const response: AuthListingsResponse = {
      listings: [
        {
          title: 'Engineer',
          company_name: 'Corp A',
          location_raw: 'Munich',
          work_arrangement: 'Hybrid',
          required_skills: ['Go'],
          posted_at: '2025-01-01T00:00:00Z',
          language: 'de',
        },
        {
          title: 'Designer',
          company_name: 'Corp B',
          location_raw: null,
          work_arrangement: null,
          required_skills: [],
          posted_at: '2025-02-01T00:00:00Z',
          language: null,
        },
      ],
      country: 'DEU',
    };

    expect(response.listings).toHaveLength(2);
    expect(nonNull(response.listings[0]).title).toBe('Engineer');
    expect(nonNull(response.listings[1]).company_name).toBe('Corp B');
  });
});
