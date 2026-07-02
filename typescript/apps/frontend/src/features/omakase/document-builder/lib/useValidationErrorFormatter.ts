import type { ZodError } from 'zod';

interface FormattedValidationError {
  message: string;
  sections: Array<{
    name: string;
    errors: Array<{
      path: string;
      message: string;
    }>;
  }>;
}

export function useValidationErrorFormatter(): {
  formatValidationError: (zodError: ZodError) => FormattedValidationError;
  formatValidationErrorSummary: (zodError: ZodError) => string;
} {
  const formatValidationError = (zodError: ZodError): FormattedValidationError => {
    const errorGroups: Record<string, Array<{ path: string; message: string }>> = {};

    for (const issue of zodError.issues) {
      const path: string = issue.path.length > 0 ? issue.path.join('.') : 'root';
      const section = path.split('.')[0] || 'general';

      if (!errorGroups[section]) {
        errorGroups[section] = [];
      }

      errorGroups[section].push({
        path,
        message: issue.message,
      });
    }

    const sections = Object.entries(errorGroups).map(([section, errors]) => ({
      name: section.charAt(0).toUpperCase() + section.slice(1),
      errors,
    }));

    const message = sections
      .map((section) => {
        const errorList = section.errors.map((e) => `  • ${e.path}: ${e.message}`).join('\n');
        return `${section.name}:\n${errorList}`;
      })
      .join('\n\n');

    return {
      message: `Please fix the following data validation errors:\n\n${message}`,
      sections,
    };
  };

  const formatValidationErrorSummary = (zodError: ZodError): string => {
    const { message } = formatValidationError(zodError);
    return message;
  };

  return {
    formatValidationError,
    formatValidationErrorSummary,
  };
}
