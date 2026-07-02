import { BFF_MAX_RESPONSE_BYTES } from './constants';
import type { AuthListingItem, AuthListingsResponse } from './types';

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isAuthListingItem(value: unknown): value is AuthListingItem {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const item = value as Record<string, unknown>;
  return (
    typeof item.title === 'string' &&
    typeof item.company_name === 'string' &&
    isNullableString(item.location_raw) &&
    isNullableString(item.work_arrangement) &&
    Array.isArray(item.required_skills) &&
    item.required_skills.every((skill) => typeof skill === 'string') &&
    typeof item.posted_at === 'string' &&
    isNullableString(item.language)
  );
}

function isAuthListingsResponse(value: unknown, country: string): value is AuthListingsResponse {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const response = value as Record<string, unknown>;
  return (
    response.country === country &&
    Array.isArray(response.listings) &&
    response.listings.every(isAuthListingItem)
  );
}

async function readBoundedJson(response: Response): Promise<unknown> {
  const contentLength = response.headers.get('Content-Length');
  if (contentLength !== null && Number(contentLength) > BFF_MAX_RESPONSE_BYTES) {
    throw new Error('BFF response exceeded size limit');
  }
  if (!response.body) {
    throw new Error('BFF returned an empty response body');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const chunks: string[] = [];
  let bytesRead = 0;
  let readResult = await reader.read();

  while (!readResult.done) {
    bytesRead += readResult.value.byteLength;
    if (bytesRead > BFF_MAX_RESPONSE_BYTES) {
      await reader.cancel().catch(() => undefined);
      throw new Error('BFF response exceeded size limit');
    }
    chunks.push(decoder.decode(readResult.value, { stream: true }));
    readResult = await reader.read();
  }
  chunks.push(decoder.decode());
  return JSON.parse(chunks.join('')) as unknown;
}

/** Bound, validate, and project an upstream payload onto the public response contract. */
export async function readAuthListingsResponse(
  response: Response,
  country: string,
): Promise<AuthListingsResponse> {
  const data = await readBoundedJson(response);
  if (!isAuthListingsResponse(data, country)) {
    throw new Error('BFF returned an invalid response payload');
  }
  return {
    country,
    listings: data.listings.map((item) => ({
      title: item.title,
      company_name: item.company_name,
      location_raw: item.location_raw,
      work_arrangement: item.work_arrangement,
      required_skills: item.required_skills,
      posted_at: item.posted_at,
      language: item.language,
    })),
  };
}
