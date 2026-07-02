import type { JobCorrelationResponse, ProfileResponse, UserResponse } from '@/shared/api';

interface ContentSchema {
  properties?: Record<string, unknown>;
  required?: readonly string[];
}

type TemplateVariables = Record<string, unknown>;

type DataSource = ProfileResponse | null | undefined;
type AccountSource = UserResponse | null | undefined;
type MatchSource = JobCorrelationResponse | null | undefined;

/**
 * Maps the canonical account display name to the template's full name.
 * Returns null when Display Name is absent so generation can require profile correction.
 */
function resolveFullName(account: AccountSource): string | null {
  if (!account) {
    return null;
  }
  return account.display_name?.trim() || null;
}

function resolveProfessionalTitle(profile: DataSource): string | null {
  if (profile?.pref_name) {
    return profile.pref_name;
  }
  if (profile?.search_keywords && profile.search_keywords.length > 0) {
    return profile.search_keywords[0] ?? null;
  }
  return null;
}

function resolveSkills(profile: DataSource): string[] | null {
  if (profile?.user_skills && profile.user_skills.length > 0) {
    return profile.user_skills;
  }
  return null;
}

function buildMappings(
  profile: DataSource,
  match: MatchSource,
  account: AccountSource,
): Record<string, () => unknown> {
  return {
    full_name: () => resolveFullName(account),
    'contact.email': () => account?.email,
    contact_email: () => account?.email,
    email: () => account?.email,
    professional_title: () => resolveProfessionalTitle(profile),
    skills: () => resolveSkills(profile),
    company_name: () => match?.listing_company,
    job_title: () => match?.listing_title,
    job_url: () => match?.listing_url,
    job_location: () => match?.listing_location,
  };
}

/**
 * Maps known template variable names to user profile, account, and match data.
 *
 * Only variables that (a) exist in the schema's properties AND (b) have a non-empty
 * value from the data sources are included. Fields without data are omitted entirely
 * so the form renders them as empty inputs rather than "undefined" or "null" strings.
 */
function mapDataToTemplateVariables(
  schema: ContentSchema | null | undefined,
  profile?: DataSource,
  match?: MatchSource,
  account?: AccountSource,
): TemplateVariables {
  const properties = schema?.properties;
  if (!properties) {
    return {};
  }

  const schemaKeys = new Set(Object.keys(properties));
  const result: TemplateVariables = {};
  const mappings = buildMappings(profile, match, account);

  for (const key of schemaKeys) {
    const resolver = mappings[key];
    if (resolver) {
      const value = resolver();
      if (value !== undefined && value !== null && value !== '') {
        result[key] = value;
      }
    }
  }

  return result;
}

export type { ContentSchema };
export { mapDataToTemplateVariables };
