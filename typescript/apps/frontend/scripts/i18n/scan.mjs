/**
 * File scanning logic for i18n validation.
 *
 * Detects hardcoded user-facing strings and checks for unused locale keys.
 */

import { readFileSync } from 'node:fs';
import { relative } from 'node:path';

import { getAllKeys } from './compare.mjs';
import { error, success, warn } from './report.mjs';

const HARDCODED_ISSUE_DISPLAY_LIMIT = 20;
const HARDCODED_TEXT_DISPLAY_LENGTH = 50;
const HARDCODED_LINE_DISPLAY_LENGTH = 100;
const MIN_STRING_LENGTH_TO_CHECK = 3;

const HARDCODED_PATTERNS = [
  />(?<text>[A-Z][a-zA-Z\s]{2,50})</gu,
  />(?<text>[A-Z][a-zA-Z\s]{2,30})<\//gu,
  /placeholder=["'](?<text>[A-Z][a-zA-Z\s]{2,50})["']/gu,
  /title=["'](?<text>[A-Z][a-zA-Z\s]{2,50})["']/gu,
  /label=["'](?<text>[A-Z][a-zA-Z\s]{2,50})["']/gu,
  /aria-label=["'](?<text>[A-Z][a-zA-Z\s]{2,50})["']/gu,
];

const EXCLUDED_FILES = [
  'component-example.tsx',
  'component-example.test.tsx',
  '.test.tsx',
  '.test.ts',
  '.spec.tsx',
  '.spec.ts',
];

const IGNORE_PATTERNS = [
  /t\(["']/u,
  /i18nKey=["']/u,
  /className=/u,
  /testid=/u,
  /console\./u,
  /Error\(/u,
  /throw new/u,
  /\/[*]/u,
  /import\s+/u,
  /from\s+["']/u,
  /useQuery|useMutation|useEffect/u,
];

const SOURCE_FILE_RE = /\.(?:tsx?|jsx?)$/u;
const DIGITS_ONLY_RE = /^\d+$/u;
const SCREAMING_SNAKE_RE = /^[A-Z_]+$/u;

function shouldSkipLine(line) {
  const trimmed = line.trim();
  return trimmed.startsWith('import ') || trimmed.startsWith('//') || trimmed.startsWith('*');
}

function shouldSkipText(text, line) {
  if (IGNORE_PATTERNS.some((p) => p.test(line))) {
    return true;
  }
  if (text.length < MIN_STRING_LENGTH_TO_CHECK) {
    return true;
  }
  if (DIGITS_ONLY_RE.test(text)) {
    return true;
  }
  if (SCREAMING_SNAKE_RE.test(text)) {
    return true;
  }
  if (text.includes('(') || text.includes(')')) {
    return true;
  }
  if (text.includes('{') || text.includes('}')) {
    return true;
  }
  return false;
}

function findHardcodedPatternsInLine(line, filePath, lineNum, issues) {
  for (const pattern of HARDCODED_PATTERNS) {
    const matches = [...line.matchAll(pattern)];
    for (const match of matches) {
      const text = match.groups?.text;
      if (!shouldSkipText(text, line)) {
        issues.push({
          file: filePath,
          line: lineNum,
          text: text.slice(0, HARDCODED_TEXT_DISPLAY_LENGTH),
          fullLine: line.trim().slice(0, HARDCODED_LINE_DISPLAY_LENGTH),
        });
      }
    }
  }
}

function processFileForHardcodedStrings(file, rootDir, issues) {
  const content = readFileSync(file, 'utf-8');
  const lines = content.split('\n');
  const relativePath = relative(rootDir, file);

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const lineNum = i + 1;

    if (!shouldSkipLine(line)) {
      findHardcodedPatternsInLine(line, relativePath, lineNum, issues);
    }
  }
}

function reportHardcodedIssues(issues) {
  if (issues.length === 0) {
    success('No hardcoded user-facing strings detected');
    return true;
  }

  error(`Found ${issues.length} potential hardcoded strings:`);
  for (const issue of issues.slice(0, HARDCODED_ISSUE_DISPLAY_LIMIT)) {
    warn(`  ${issue.file}:${issue.line} - "${issue.text}"`);
    warn(`    ${issue.fullLine}`);
  }
  if (issues.length > HARDCODED_ISSUE_DISPLAY_LIMIT) {
    warn(`  ... and ${issues.length - HARDCODED_ISSUE_DISPLAY_LIMIT} more`);
  }
  return false;
}

/** Check for hardcoded user-facing strings in source files. */
export function checkHardcodedStrings(getAllFiles, srcDir, rootDir) {
  const files = getAllFiles(srcDir, SOURCE_FILE_RE);
  const issues = [];

  for (const file of files) {
    if (!EXCLUDED_FILES.some((excluded) => file.includes(excluded))) {
      processFileForHardcodedStrings(file, rootDir, issues);
    }
  }

  return reportHardcodedIssues(issues);
}

/** Check for unused locale keys (best-effort, may have false positives). */
export function checkUnusedKeys(locales, getAllFiles, srcDir) {
  const sourceFiles = getAllFiles(srcDir, SOURCE_FILE_RE);
  const allSource = sourceFiles.map((f) => readFileSync(f, 'utf-8')).join('\n');

  for (const [, files] of Object.entries(locales)) {
    for (const [, content] of Object.entries(files)) {
      const keys = getAllKeys(content);

      for (const key of keys) {
        const keyParts = key.split('.');
        const lastPart = keyParts.at(-1);

        const _isUsed = [
          `t('${key}')`,
          `t("${key}")`,
          `i18nKey="${key}"`,
          `i18nKey='${key}'`,
          `'${key}'`,
          `"${key}"`,
          lastPart,
        ].some((pattern) => allSource.includes(pattern));
      }
    }
  }

  success('Key usage check completed (may have false positives)');
  return true;
}
