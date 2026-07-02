import { trace } from '@opentelemetry/api';
import type { LogEntry } from './types';

function getTraceContext(): { traceId?: string; spanId?: string } {
  const span = trace.getActiveSpan();
  if (!span) {
    return {};
  }
  const ctx = span.spanContext();
  return { traceId: ctx.traceId, spanId: ctx.spanId };
}

/** Structured JSON logger compatible with Cloudflare Logpush. */
function log(level: LogEntry['level'], message: string, extra?: Record<string, unknown>): void {
  const entry: LogEntry = {
    level,
    message,
    timestamp: new Date().toISOString(),
    ...getTraceContext(),
    ...extra,
  };
  // biome-ignore lint/suspicious/noConsole: Cloudflare Workers use console for structured log output via Logpush
  console.log(JSON.stringify(entry));
}

export const workerLogger = {
  info(message: string, extra?: Record<string, unknown>): void {
    log('info', message, extra);
  },

  warn(message: string, extra?: Record<string, unknown>): void {
    log('warn', message, extra);
  },

  error(message: string, extra?: Record<string, unknown>): void {
    log('error', message, extra);
  },
};
