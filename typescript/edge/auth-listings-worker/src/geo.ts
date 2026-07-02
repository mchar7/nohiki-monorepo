import { DEFAULT_COUNTRY_ALPHA3 } from './constants';

/**
 * ISO 3166-1 alpha-2 to alpha-3 mapping for supported countries.
 * Must match the CountryCode proto enum (14 countries).
 */
export const ALPHA2_TO_ALPHA3: Readonly<Record<string, string>> = {
  US: 'USA',
  CA: 'CAN',
  GB: 'GBR',
  DE: 'DEU',
  FR: 'FRA',
  NL: 'NLD',
  IE: 'IRL',
  CH: 'CHE',
  AU: 'AUS',
  NZ: 'NZL',
  SG: 'SGP',
  IN: 'IND',
  AE: 'ARE',
  IL: 'ISR',
};

/** Resolve Cloudflare alpha-2 country code to alpha-3, defaulting to USA for unmapped values. */
export function resolveCountry(cfAlpha2: string | undefined): string {
  if (!cfAlpha2) {
    return DEFAULT_COUNTRY_ALPHA3;
  }
  return ALPHA2_TO_ALPHA3[cfAlpha2] ?? DEFAULT_COUNTRY_ALPHA3;
}
