const HTTP_STATUS = {
  OK: 200,
  CREATED: 201,
  NO_CONTENT: 204,
  BAD_REQUEST: 400,
  UNAUTHORIZED: 401,
  FORBIDDEN: 403,
  NOT_FOUND: 404,
  CONFLICT: 409,
  UNPROCESSABLE_ENTITY: 422,
  TOO_MANY_REQUESTS: 429,
  INTERNAL_SERVER_ERROR: 500,
  BAD_GATEWAY: 502,
  SERVICE_UNAVAILABLE: 503,
  GATEWAY_TIMEOUT: 504,
} as const;

const API_ERROR_TYPES = {
  NETWORK_ERROR: 'network_error',
  VALIDATION_ERROR: 'validation_error',
  AUTHENTICATION_ERROR: 'authentication_error',
  AUTHORIZATION_ERROR: 'authorization_error',
  NOT_FOUND_ERROR: 'not_found_error',
  CONFLICT_ERROR: 'conflict_error',
  RATE_LIMIT_ERROR: 'rate_limit_error',
  SERVER_ERROR: 'server_error',
  SERVICE_UNAVAILABLE: 'service_unavailable',
  TIMEOUT_ERROR: 'timeout_error',
  TEMPLATE_TIMEOUT: 'template_timeout',
  TEMPLATE_TOO_COMPLEX: 'template_too_complex',
  PDF_CONVERSION_ERROR: 'pdf_conversion_error',
} as const;

const CONTENT_TYPES = {
  JSON: 'application/json',
  PDF: 'application/pdf',
  HTML: 'text/html',
  TEXT: 'text/plain',
  FORM_DATA: 'multipart/form-data',
  URL_ENCODED: 'application/x-www-form-urlencoded',
} as const;

type ApiErrorType = (typeof API_ERROR_TYPES)[keyof typeof API_ERROR_TYPES];

export type { ApiErrorType };
export { CONTENT_TYPES, HTTP_STATUS };
