import { renderHook } from '@testing-library/react';
import { describe, expect } from 'vitest';
import { ZodError, z } from 'zod';
import { nonNull } from '@/shared/test-utils';
import { useValidationErrorFormatter } from './useValidationErrorFormatter.ts';

function createZodError(issues: Array<{ path: string[]; message: string }>): ZodError {
  return new ZodError(
    issues.map((issue) => ({
      code: 'custom',
      path: issue.path,
      message: issue.message,
    })),
  );
}

describe('formatValidationError - basic formatting', () => {
  test('formats single error', () => {
    const { result } = renderHook(() => useValidationErrorFormatter());

    const zodError = createZodError([{ path: ['name'], message: 'Required' }]);
    const formatted = result.current.formatValidationError(zodError);

    expect(formatted.sections).toHaveLength(1);
    expect(nonNull(formatted.sections[0]).name).toBe('Name');
    expect(nonNull(formatted.sections[0]).errors).toHaveLength(1);
    expect(nonNull(nonNull(formatted.sections[0]).errors[0]).message).toBe('Required');
  });

  test('handles root-level errors', () => {
    const { result } = renderHook(() => useValidationErrorFormatter());

    const zodError = createZodError([{ path: [], message: 'Invalid data' }]);
    const formatted = result.current.formatValidationError(zodError);

    expect(formatted.sections).toHaveLength(1);
    expect(nonNull(formatted.sections[0]).name).toBe('Root');
  });

  test('capitalizes section names', () => {
    const { result } = renderHook(() => useValidationErrorFormatter());

    const zodError = createZodError([{ path: ['settings', 'theme'], message: 'Invalid' }]);
    const formatted = result.current.formatValidationError(zodError);

    expect(nonNull(formatted.sections[0]).name).toBe('Settings');
  });
});

describe('formatValidationError - grouping and messages', () => {
  test('groups errors by section', () => {
    const { result } = renderHook(() => useValidationErrorFormatter());

    const zodError = createZodError([
      { path: ['personal', 'name'], message: 'Required' },
      { path: ['personal', 'email'], message: 'Invalid email' },
      { path: ['address', 'city'], message: 'Required' },
    ]);
    const formatted = result.current.formatValidationError(zodError);

    expect(formatted.sections).toHaveLength(2);
    const personalSection = formatted.sections.find((s) => s.name === 'Personal');
    const addressSection = formatted.sections.find((s) => s.name === 'Address');

    expect(personalSection?.errors).toHaveLength(2);
    expect(addressSection?.errors).toHaveLength(1);
  });

  test('includes formatted message string', () => {
    const { result } = renderHook(() => useValidationErrorFormatter());

    const zodError = createZodError([{ path: ['name'], message: 'Required' }]);
    const formatted = result.current.formatValidationError(zodError);

    expect(formatted.message).toContain('validation errors');
    expect(formatted.message).toContain('name');
    expect(formatted.message).toContain('Required');
  });
});

describe('formatValidationErrorSummary', () => {
  test('returns message from formatValidationError', () => {
    const { result } = renderHook(() => useValidationErrorFormatter());

    const zodError = createZodError([{ path: ['name'], message: 'Required' }]);
    const summary = result.current.formatValidationErrorSummary(zodError);

    expect(summary).toContain('validation errors');
    expect(summary).toContain('name');
  });
});

describe('useValidationErrorFormatter - real Zod schema', () => {
  test('formats errors from actual Zod validation', () => {
    const { result } = renderHook(() => useValidationErrorFormatter());

    const schema = z.object({
      name: z.string().min(1, 'Name is required'),
      email: z.email({ error: 'Invalid email format' }),
    });

    const parseResult = schema.safeParse({ name: '', email: 'invalid' });
    expect(parseResult.success).toBe(false);

    // Type narrowing: after asserting success is false, error is available
    const formatted = result.current.formatValidationError(
      (parseResult as { success: false; error: ZodError }).error,
    );
    expect(formatted.sections.length).toBeGreaterThan(0);
  });
});
