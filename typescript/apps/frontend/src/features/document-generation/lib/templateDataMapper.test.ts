import { describe, expect } from 'vitest';
import type { JobCorrelationResponse, ProfileResponse, UserResponse } from '@/shared/api';
import type { ContentSchema } from './templateDataMapper.ts';
import { mapDataToTemplateVariables } from './templateDataMapper.ts';

const FULL_SCHEMA: ContentSchema = {
  properties: {
    full_name: { type: 'string', title: 'Full Name' },
    email: { type: 'string', title: 'Email' },
    professional_title: { type: 'string', title: 'Professional Title' },
    skills: { type: 'array', title: 'Skills' },
    company_name: { type: 'string', title: 'Company' },
    job_title: { type: 'string', title: 'Job Title' },
    job_url: { type: 'string', title: 'Job URL' },
    job_location: { type: 'string', title: 'Location' },
    contact_email: { type: 'string', title: 'Contact Email' },
  },
};

const COMPLETE_PROFILE: ProfileResponse = {
  id: 'prof-1',
  user_id: 'user-1',
  pref_name: 'Senior Frontend Developer',
  search_keywords: ['frontend', 'react', 'typescript'],
  disallowed_keywords: [],
  work_arrangements: [],
  user_skills: ['react', 'typescript', 'css'],
  notification_threshold: 0.7,
  auto_tailor_threshold: null,
  open_to_relocation: false,
};

const COMPLETE_ACCOUNT: UserResponse = {
  id: 'user-1',
  email: 'jane@example.com',
  first_name: 'Jane',
  last_name: 'Doe',
  display_name: 'Jane Doe',
  is_active: true,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
};

const COMPLETE_MATCH: JobCorrelationResponse = {
  id: 'match-1',
  pref_id: 'prof-1',
  listing_id: 'listing-1',
  fit_score: 0.85,
  status: 'PENDING',
  score_breakdown: {},
  listing_title: 'Senior React Engineer',
  listing_company: 'Acme Corp',
  listing_url: 'https://example.com/job/123',
  listing_location: 'Berlin, Germany',
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
};

describe('mapDataToTemplateVariables - complete data', () => {
  test('maps all available fields from profile, account, and match', () => {
    const result = mapDataToTemplateVariables(
      FULL_SCHEMA,
      COMPLETE_PROFILE,
      COMPLETE_MATCH,
      COMPLETE_ACCOUNT,
    );

    expect(result).toEqual({
      full_name: 'Jane Doe',
      email: 'jane@example.com',
      contact_email: 'jane@example.com',
      professional_title: 'Senior Frontend Developer',
      skills: ['react', 'typescript', 'css'],
      company_name: 'Acme Corp',
      job_title: 'Senior React Engineer',
      job_url: 'https://example.com/job/123',
      job_location: 'Berlin, Germany',
    });
  });

  test('prefers display_name over first+last name', () => {
    const schema: ContentSchema = { properties: { full_name: {} } };
    const account = { ...COMPLETE_ACCOUNT, display_name: 'J. Doe' };

    const result = mapDataToTemplateVariables(schema, null, null, account);
    expect(result.full_name).toBe('J. Doe');
  });

  test.each([
    null,
    '',
    '   ',
  ])('does not fabricate full_name from structured fields when display_name is %s', (displayName) => {
    const schema: ContentSchema = { properties: { full_name: {} } };
    const account = { ...COMPLETE_ACCOUNT, display_name: displayName };

    const result = mapDataToTemplateVariables(schema, null, null, account);
    expect(result).not.toHaveProperty('full_name');
  });

  test('falls back to first keyword when pref_name is empty', () => {
    const schema: ContentSchema = { properties: { professional_title: {} } };
    const profile = { ...COMPLETE_PROFILE, pref_name: '' };

    const result = mapDataToTemplateVariables(schema, profile, null, null);
    expect(result.professional_title).toBe('frontend');
  });
});

describe('mapDataToTemplateVariables - partial data', () => {
  test('maps only account fields when profile and match are null', () => {
    const result = mapDataToTemplateVariables(FULL_SCHEMA, null, null, COMPLETE_ACCOUNT);

    expect(result).toEqual({
      full_name: 'Jane Doe',
      email: 'jane@example.com',
      contact_email: 'jane@example.com',
    });
    expect(result).not.toHaveProperty('professional_title');
    expect(result).not.toHaveProperty('company_name');
  });

  test('maps only match fields when profile and account are null', () => {
    const result = mapDataToTemplateVariables(FULL_SCHEMA, null, COMPLETE_MATCH, null);

    expect(result).toEqual({
      company_name: 'Acme Corp',
      job_title: 'Senior React Engineer',
      job_url: 'https://example.com/job/123',
      job_location: 'Berlin, Germany',
    });
    expect(result).not.toHaveProperty('full_name');
  });

  test('maps only profile fields when account and match are null', () => {
    const result = mapDataToTemplateVariables(FULL_SCHEMA, COMPLETE_PROFILE, null, null);

    expect(result).toEqual({
      professional_title: 'Senior Frontend Developer',
      skills: ['react', 'typescript', 'css'],
    });
  });

  test('skips fields when match has null listing_company', () => {
    const match = { ...COMPLETE_MATCH, listing_company: null };
    const schema: ContentSchema = { properties: { company_name: {}, job_title: {} } };

    const result = mapDataToTemplateVariables(schema, null, match, null);

    expect(result).toEqual({ job_title: 'Senior React Engineer' });
    expect(result).not.toHaveProperty('company_name');
  });

  test('skips skills when user_skills is empty array', () => {
    const profile = { ...COMPLETE_PROFILE, user_skills: [] };
    const schema: ContentSchema = { properties: { skills: {} } };

    const result = mapDataToTemplateVariables(schema, profile, null, null);
    expect(result).not.toHaveProperty('skills');
  });
});

describe('mapDataToTemplateVariables - no data', () => {
  test('returns empty object when all sources are null', () => {
    const result = mapDataToTemplateVariables(FULL_SCHEMA, null, null, null);
    expect(result).toEqual({});
  });

  test('returns empty object when all sources are undefined', () => {
    const result = mapDataToTemplateVariables(FULL_SCHEMA, undefined, undefined, undefined);
    expect(result).toEqual({});
  });

  test('returns empty object when schema is null', () => {
    const result = mapDataToTemplateVariables(
      null,
      COMPLETE_PROFILE,
      COMPLETE_MATCH,
      COMPLETE_ACCOUNT,
    );
    expect(result).toEqual({});
  });

  test('returns empty object when schema has no properties', () => {
    const result = mapDataToTemplateVariables(
      {},
      COMPLETE_PROFILE,
      COMPLETE_MATCH,
      COMPLETE_ACCOUNT,
    );
    expect(result).toEqual({});
  });
});

describe('mapDataToTemplateVariables - absent fields guarantee', () => {
  test('does not set fields to undefined or null', () => {
    const result = mapDataToTemplateVariables(FULL_SCHEMA, null, null, null);

    for (const key of Object.keys(result)) {
      expect(result[key]).not.toBeUndefined();
      expect(result[key]).not.toBeNull();
    }
  });

  test('omits unmapped schema keys rather than setting them', () => {
    const schemaWithUnknown: ContentSchema = {
      properties: {
        full_name: {},
        custom_field_xyz: {},
        another_unknown: {},
      },
    };

    const result = mapDataToTemplateVariables(schemaWithUnknown, null, null, COMPLETE_ACCOUNT);

    expect(result).toEqual({ full_name: 'Jane Doe' });
    expect(Object.keys(result)).not.toContain('custom_field_xyz');
    expect(Object.keys(result)).not.toContain('another_unknown');
  });

  test('only includes keys present in schema properties', () => {
    const narrowSchema: ContentSchema = { properties: { job_title: {} } };

    const result = mapDataToTemplateVariables(
      narrowSchema,
      COMPLETE_PROFILE,
      COMPLETE_MATCH,
      COMPLETE_ACCOUNT,
    );

    expect(Object.keys(result)).toEqual(['job_title']);
  });
});
