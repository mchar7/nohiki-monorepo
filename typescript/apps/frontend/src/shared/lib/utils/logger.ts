/**
 * Centralized logging utility for the application
 * Provides consistent logging with different levels and better production handling
 */

const LogLevel = {
  DEBUG: 0,
  INFO: 1,
  WARN: 2,
  ERROR: 3,
} as const;

type LogLevelValue = (typeof LogLevel)[keyof typeof LogLevel];

interface LogContext {
  component?: string;
  action?: string;
  userId?: string;
  [key: string]: unknown;
}

class Logger {
  private readonly level: LogLevelValue;
  private readonly isDevelopment: boolean;

  constructor() {
    this.isDevelopment = import.meta.env.DEV;
    this.level = this.isDevelopment ? LogLevel.DEBUG : LogLevel.WARN;
  }

  private shouldLog(level: LogLevelValue): boolean {
    return level >= this.level;
  }

  private formatMessage(level: string, message: string, context?: LogContext): void {
    if (!this.isDevelopment && level === 'debug') {
      return;
    }

    const timestamp = new Date().toISOString();
    const prefix = `[${timestamp}] [${level.toUpperCase()}]`;

    // biome-ignore lint/suspicious/noConsole: logger is the centralized console wrapper
    const logMethod = console[level as 'debug' | 'info' | 'warn' | 'error'] || console.log;

    if (context) {
      const contextStr = Object.entries(context)
        .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
        .join(' ');
      logMethod(`${prefix} ${message}`, `Context: ${contextStr}`);
    } else {
      logMethod(`${prefix} ${message}`);
    }
  }

  debug(message: string, context?: LogContext): void {
    if (this.shouldLog(LogLevel.DEBUG)) {
      this.formatMessage('debug', message, context);
    }
  }

  info(message: string, context?: LogContext): void {
    if (this.shouldLog(LogLevel.INFO)) {
      this.formatMessage('info', message, context);
    }
  }

  warn(message: string, context?: LogContext): void {
    if (this.shouldLog(LogLevel.WARN)) {
      this.formatMessage('warn', message, context);
    }
  }

  error(message: string, error?: Error | unknown, context?: LogContext): void {
    if (this.shouldLog(LogLevel.ERROR)) {
      const errorContext = {
        ...context,
        error:
          error instanceof Error
            ? {
                name: error.name,
                message: error.message,
                stack: error.stack,
              }
            : error,
      };
      this.formatMessage('error', message, errorContext);
    }
  }
}

const logger: Logger = new Logger();

const logApiError = (operation: string, error: unknown, context?: LogContext): void => {
  logger.error(`API Error in ${operation}`, error, { ...context, operation });
};

const logComponentError = (component: string, error: unknown, context?: LogContext): void => {
  logger.error(`Component Error in ${component}`, error, { ...context, component });
};

const logValidationError = (field: string, error: unknown, context?: LogContext): void => {
  logger.error(`Validation Error for ${field}`, error, { ...context, field });
};

export { LogLevel, logApiError, logComponentError, logger, logValidationError };
