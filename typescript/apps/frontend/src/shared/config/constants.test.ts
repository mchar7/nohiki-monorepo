import { describe, expect } from 'vitest';
import {
  API_ERROR_TYPE,
  AUTH_CONSTRAINTS,
  CONTENT_TYPE,
  HTTP_STATUS,
  mapStatusToErrorType,
  QUERY_CONFIG,
  REQUEST_CONFIG,
} from './constants.ts';

const MS_PER_SECOND: number = 1000;
const SECONDS_PER_MINUTE: number = 60;
const MS_PER_MINUTE: number = SECONDS_PER_MINUTE * MS_PER_SECOND;

// HTTP status code expectations (raw literals acceptable when testing enum values)
const HTTP_OK: number = 200;
const HTTP_CREATED: number = 201;
const HTTP_ACCEPTED: number = 202;
const HTTP_NO_CONTENT: number = 204;
const HTTP_BAD_REQUEST: number = 400;
const HTTP_UNAUTHORIZED: number = 401;
const HTTP_FORBIDDEN: number = 403;
const HTTP_NOT_FOUND: number = 404;
const HTTP_CONFLICT: number = 409;
const HTTP_UNPROCESSABLE: number = 422;
const HTTP_TOO_MANY_REQUESTS: number = 429;
const HTTP_INTERNAL_SERVER_ERROR: number = 500;
const HTTP_BAD_GATEWAY: number = 502;
const HTTP_SERVICE_UNAVAILABLE: number = 503;
const HTTP_GATEWAY_TIMEOUT: number = 504;
const HTTP_IM_A_TEAPOT: number = 418;
const HTTP_MULTIPLE_CHOICES: number = 300;

// QUERY_CONFIG expected values
const EXPECTED_MAX_RETRIES: number = 2;
const EXPECTED_RETRY_BASE_MS: number = MS_PER_SECOND;
const EXPECTED_RETRY_MAX_SECONDS: number = 10;
const EXPECTED_RETRY_MAX_MS: number = EXPECTED_RETRY_MAX_SECONDS * MS_PER_SECOND;
const EXPECTED_DEFAULT_TIMEOUT_SECONDS: number = 30;
const EXPECTED_DEFAULT_TIMEOUT_MS: number = EXPECTED_DEFAULT_TIMEOUT_SECONDS * MS_PER_SECOND;
const EXPECTED_AUTH_TIMEOUT_SECONDS: number = 10;
const EXPECTED_AUTH_TIMEOUT_MS: number = EXPECTED_AUTH_TIMEOUT_SECONDS * MS_PER_SECOND;
const EXPECTED_QUERY_STALE_MINUTES: number = 5;
const EXPECTED_QUERY_GC_MINUTES: number = 30;

// AUTH_CONSTRAINTS expected values
const EXPECTED_PASSWORD_MIN_LENGTH: number = 8;
const EXPECTED_PASSWORD_MAX_LENGTH: number = 128;
const EXPECTED_NAME_MAX_LENGTH: number = 50;
const EXPECTED_DISPLAY_NAME_MAX_LENGTH: number = 255;

describe('constants - HTTP_STATUS', () => {
  test('contains standard success codes', () => {
    expect(HTTP_STATUS.OK).toBe(HTTP_OK);
    expect(HTTP_STATUS.CREATED).toBe(HTTP_CREATED);
    expect(HTTP_STATUS.ACCEPTED).toBe(HTTP_ACCEPTED);
    expect(HTTP_STATUS.NO_CONTENT).toBe(HTTP_NO_CONTENT);
  });

  test('contains standard client error codes', () => {
    expect(HTTP_STATUS.BAD_REQUEST).toBe(HTTP_BAD_REQUEST);
    expect(HTTP_STATUS.UNAUTHORIZED).toBe(HTTP_UNAUTHORIZED);
    expect(HTTP_STATUS.FORBIDDEN).toBe(HTTP_FORBIDDEN);
    expect(HTTP_STATUS.NOT_FOUND).toBe(HTTP_NOT_FOUND);
    expect(HTTP_STATUS.CONFLICT).toBe(HTTP_CONFLICT);
    expect(HTTP_STATUS.UNPROCESSABLE_ENTITY).toBe(HTTP_UNPROCESSABLE);
    expect(HTTP_STATUS.TOO_MANY_REQUESTS).toBe(HTTP_TOO_MANY_REQUESTS);
  });

  test('contains standard server error codes', () => {
    expect(HTTP_STATUS.INTERNAL_SERVER_ERROR).toBe(HTTP_INTERNAL_SERVER_ERROR);
    expect(HTTP_STATUS.BAD_GATEWAY).toBe(HTTP_BAD_GATEWAY);
    expect(HTTP_STATUS.SERVICE_UNAVAILABLE).toBe(HTTP_SERVICE_UNAVAILABLE);
    expect(HTTP_STATUS.GATEWAY_TIMEOUT).toBe(HTTP_GATEWAY_TIMEOUT);
  });
});

describe('constants - API_ERROR_TYPE', () => {
  test('contains all error type strings', () => {
    expect(API_ERROR_TYPE.NETWORK).toBe('network_error');
    expect(API_ERROR_TYPE.VALIDATION).toBe('validation_error');
    expect(API_ERROR_TYPE.AUTHENTICATION).toBe('authentication_error');
    expect(API_ERROR_TYPE.AUTHORIZATION).toBe('authorization_error');
    expect(API_ERROR_TYPE.NOT_FOUND).toBe('not_found_error');
    expect(API_ERROR_TYPE.CONFLICT).toBe('conflict_error');
    expect(API_ERROR_TYPE.RATE_LIMIT).toBe('rate_limit_error');
    expect(API_ERROR_TYPE.SERVER).toBe('server_error');
    expect(API_ERROR_TYPE.SERVICE_UNAVAILABLE).toBe('service_unavailable');
    expect(API_ERROR_TYPE.TIMEOUT).toBe('timeout_error');
  });
});

describe('constants - mapStatusToErrorType', () => {
  test('maps 400 to validation error', () => {
    expect(mapStatusToErrorType(HTTP_BAD_REQUEST)).toBe(API_ERROR_TYPE.VALIDATION);
  });

  test('maps 422 to validation error', () => {
    expect(mapStatusToErrorType(HTTP_UNPROCESSABLE)).toBe(API_ERROR_TYPE.VALIDATION);
  });

  test('maps 401 to authentication error', () => {
    expect(mapStatusToErrorType(HTTP_UNAUTHORIZED)).toBe(API_ERROR_TYPE.AUTHENTICATION);
  });

  test('maps 403 to authorization error', () => {
    expect(mapStatusToErrorType(HTTP_FORBIDDEN)).toBe(API_ERROR_TYPE.AUTHORIZATION);
  });

  test('maps 404 to not found error', () => {
    expect(mapStatusToErrorType(HTTP_NOT_FOUND)).toBe(API_ERROR_TYPE.NOT_FOUND);
  });

  test('maps 409 to conflict error', () => {
    expect(mapStatusToErrorType(HTTP_CONFLICT)).toBe(API_ERROR_TYPE.CONFLICT);
  });

  test('maps 429 to rate limit error', () => {
    expect(mapStatusToErrorType(HTTP_TOO_MANY_REQUESTS)).toBe(API_ERROR_TYPE.RATE_LIMIT);
  });

  test('maps 503 to service unavailable error', () => {
    expect(mapStatusToErrorType(HTTP_SERVICE_UNAVAILABLE)).toBe(API_ERROR_TYPE.SERVICE_UNAVAILABLE);
  });

  test('maps 504 to timeout error', () => {
    expect(mapStatusToErrorType(HTTP_GATEWAY_TIMEOUT)).toBe(API_ERROR_TYPE.TIMEOUT);
  });

  test('maps 5xx codes to server error', () => {
    expect(mapStatusToErrorType(HTTP_INTERNAL_SERVER_ERROR)).toBe(API_ERROR_TYPE.SERVER);
    expect(mapStatusToErrorType(HTTP_BAD_GATEWAY)).toBe(API_ERROR_TYPE.SERVER);
  });

  test('maps unknown 4xx codes to network error', () => {
    expect(mapStatusToErrorType(HTTP_IM_A_TEAPOT)).toBe(API_ERROR_TYPE.NETWORK);
  });

  test('maps unknown codes below 400 to network error', () => {
    expect(mapStatusToErrorType(HTTP_MULTIPLE_CHOICES)).toBe(API_ERROR_TYPE.NETWORK);
  });
});

describe('constants - QUERY_CONFIG', () => {
  test('has valid timing values', () => {
    expect(QUERY_CONFIG.STALE_TIME_MS).toBe(EXPECTED_QUERY_STALE_MINUTES * MS_PER_MINUTE);
    expect(QUERY_CONFIG.GC_TIME_MS).toBe(EXPECTED_QUERY_GC_MINUTES * MS_PER_MINUTE);
    expect(QUERY_CONFIG.MAX_RETRIES).toBe(EXPECTED_MAX_RETRIES);
    expect(QUERY_CONFIG.RETRY_DELAY_BASE_MS).toBe(EXPECTED_RETRY_BASE_MS);
    expect(QUERY_CONFIG.RETRY_DELAY_MAX_MS).toBe(EXPECTED_RETRY_MAX_MS);
  });
});

describe('constants - REQUEST_CONFIG', () => {
  test('has valid timeout values', () => {
    expect(REQUEST_CONFIG.DEFAULT_TIMEOUT_MS).toBe(EXPECTED_DEFAULT_TIMEOUT_MS);
    expect(REQUEST_CONFIG.AUTH_TIMEOUT_MS).toBe(EXPECTED_AUTH_TIMEOUT_MS);
  });
});

describe('constants - CONTENT_TYPE', () => {
  test('has standard content types', () => {
    expect(CONTENT_TYPE.JSON).toBe('application/json');
    expect(CONTENT_TYPE.PDF).toBe('application/pdf');
    expect(CONTENT_TYPE.HTML).toBe('text/html');
    expect(CONTENT_TYPE.FORM_DATA).toBe('multipart/form-data');
  });
});

describe('constants - AUTH_CONSTRAINTS', () => {
  test('has valid password constraints', () => {
    expect(AUTH_CONSTRAINTS.PASSWORD_MIN_LENGTH).toBe(EXPECTED_PASSWORD_MIN_LENGTH);
    expect(AUTH_CONSTRAINTS.PASSWORD_MAX_LENGTH).toBe(EXPECTED_PASSWORD_MAX_LENGTH);
  });

  test('has valid name constraints', () => {
    expect(AUTH_CONSTRAINTS.NAME_MAX_LENGTH).toBe(EXPECTED_NAME_MAX_LENGTH);
    expect(AUTH_CONSTRAINTS.DISPLAY_NAME_MAX_LENGTH).toBe(EXPECTED_DISPLAY_NAME_MAX_LENGTH);
  });
});
