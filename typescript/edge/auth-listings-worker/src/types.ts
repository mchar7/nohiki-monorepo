export interface AuthListingItem {
  readonly title: string;
  readonly company_name: string;
  readonly location_raw: string | null;
  readonly work_arrangement: string | null;
  readonly required_skills: readonly string[];
  readonly posted_at: string;
  readonly language: string | null;
}

export interface AuthListingsResponse {
  readonly listings: readonly AuthListingItem[];
  readonly country: string;
}

export interface WorkerEnv {
  readonly BFF_ORIGIN: string;
  readonly AUTH_LISTINGS_SECRET: string;
  readonly ALLOWED_ORIGINS: string;
  readonly OTEL_EXPORTER_OTLP_ENDPOINT: string;
  readonly OTEL_EXPORTER_AUTH_TOKEN?: string;
}

export interface LogEntry {
  readonly level: 'info' | 'warn' | 'error';
  readonly message: string;
  readonly timestamp: string;
  readonly country?: string;
  readonly cache?: 'hit' | 'miss' | 'error';
  readonly traceId?: string;
  readonly spanId?: string;
  readonly extra?: Record<string, unknown>;
}
