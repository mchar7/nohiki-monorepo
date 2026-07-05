import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ExtendedValidationIssue } from '../model/index.ts';

interface TemplateValidationResult {
  readonly validationIssues: readonly ExtendedValidationIssue[];
  readonly isValidating: boolean;
  readonly errorCount: number;
  readonly warningCount: number;
  readonly validateTemplate: () => void;
  readonly clearValidation: () => void;
}

type TranslationFn = (key: string) => string;

function checkJinjaBlockMismatch(
  content: string,
  t: TranslationFn,
): ExtendedValidationIssue | null {
  const openBlocks = (content.match(/\{%\s*(if|for|block|macro|call|filter)\b/gu) ?? []).length;
  const closeBlocks = (content.match(/\{%\s*end(if|for|block|macro|call|filter)\s*%\}/gu) ?? [])
    .length;

  if (openBlocks === closeBlocks) {
    return null;
  }

  return {
    path: '$',
    keyword: 'jinja_block_mismatch',
    message: t('validation.unclosedBlock'),
    level: 'error',
    line: null,
    column: null,
  };
}

function checkJinjaExpressionMismatches(
  lines: string[],
  t: TranslationFn,
): ExtendedValidationIssue[] {
  const issues: ExtendedValidationIssue[] = [];

  for (const [index, line] of lines.entries()) {
    const openExpr = (line.match(/\{\{/gu) ?? []).length;
    const closeExpr = (line.match(/\}\}/gu) ?? []).length;
    if (openExpr !== closeExpr) {
      issues.push({
        path: `line ${index + 1}`,
        keyword: 'jinja_expression_mismatch',
        message: t('validation.unclosedExpression'),
        level: 'error',
        line: index + 1,
        column: null,
      });
    }
  }

  return issues;
}

function checkMissingDoctype(content: string, t: TranslationFn): ExtendedValidationIssue | null {
  if (content.includes('<!DOCTYPE') || content.includes('<!doctype')) {
    return null;
  }

  return {
    path: '$',
    keyword: 'missing_doctype',
    message: t('validation.missingDoctype'),
    level: 'warning',
    line: null,
    column: null,
  };
}

/**
 * Encapsulates client-side Jinja2/HTML template validation logic.
 *
 * Checks for unclosed Jinja2 blocks, mismatched expressions,
 * and basic HTML structure issues (missing DOCTYPE).
 */
export function useTemplateValidation(templateContent: string): TemplateValidationResult {
  const { t } = useTranslation('omakase.templateStudio');
  const [validationIssues, setValidationIssues] = useState<ExtendedValidationIssue[]>([]);
  const [isValidating, setIsValidating] = useState(false);

  const validateTemplate = (): void => {
    if (!templateContent.trim()) {
      setValidationIssues([]);
      return;
    }

    setIsValidating(true);

    const lines = templateContent.split('\n');
    const issues: ExtendedValidationIssue[] = [];

    const blockIssue = checkJinjaBlockMismatch(templateContent, t);
    if (blockIssue) {
      issues.push(blockIssue);
    }

    issues.push(...checkJinjaExpressionMismatches(lines, t));

    const doctypeIssue = checkMissingDoctype(templateContent, t);
    if (doctypeIssue) {
      issues.push(doctypeIssue);
    }

    setValidationIssues(issues);
    setIsValidating(false);
  };

  const clearValidation = (): void => {
    setValidationIssues([]);
  };

  let errorCount = 0;
  let warningCount = 0;
  for (const issue of validationIssues) {
    if (issue.level === 'error') {
      errorCount += 1;
    } else if (issue.level === 'warning') {
      warningCount += 1;
    }
  }

  return {
    validationIssues,
    isValidating,
    errorCount,
    warningCount,
    validateTemplate,
    clearValidation,
  };
}
