/**
 * File scanning logic for i18n validation.
 *
 * Unused-key detection is conservative: exact full or relative key literals count as use,
 * including literals carried through maps and helpers. i18next plural variants count as used
 * when their base key is referenced. Dynamic translation templates retain keys below their
 * static dotted prefix; namespace-only prefixes require finite literal carriers. A key is
 * reported only when none of those source patterns covers it.
 */

import { readFileSync } from 'node:fs';
import { relative } from 'node:path';

import { getAllKeys } from './compare.mjs';
import { error, success, warn } from './report.mjs';

const HARDCODED_ISSUE_DISPLAY_LIMIT = 20;
const HARDCODED_TEXT_DISPLAY_LENGTH = 50;
const HARDCODED_LINE_DISPLAY_LENGTH = 100;
const MIN_STRING_LENGTH_TO_CHECK = 3;
const PLURAL_SUFFIX_RE = /_(?:zero|one|two|few|many|other)$/u;
const STATIC_KEY_LITERAL_RE = /(?<quote>['"])(?<key>[A-Za-z0-9_.:-]+)\k<quote>/gu;
const DYNAMIC_TRANSLATION_PREFIX_RE =
  /(?:\bi18n[.]t|\bt(?:[A-Z][A-Za-z0-9_]*)?)[ \t]*\([ \t\r\n]*`(?<prefix>[A-Za-z0-9_.:-]*)[$][{]/gu;

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

function getTranslationKeys(locales) {
  const keys = new Set();

  for (const files of Object.values(locales)) {
    for (const [file, messages] of Object.entries(files)) {
      const namespace = file.endsWith('.json') ? file.slice(0, -'.json'.length) : file;
      for (const key of getAllKeys(messages)) {
        keys.add(`${namespace}:${key}`);
      }
    }
  }

  return keys;
}

function addReference(index, reference, translationKey) {
  const matchingKeys = index.get(reference);
  if (matchingKeys) {
    matchingKeys.push(translationKey);
  } else {
    index.set(reference, [translationKey]);
  }
}

function buildReferenceIndex(translationKeys) {
  const index = new Map();

  for (const translationKey of translationKeys) {
    const separatorIndex = translationKey.indexOf(':');
    const relativeKey = translationKey.slice(separatorIndex + 1);
    addReference(index, translationKey, translationKey);
    addReference(index, relativeKey, translationKey);

    if (PLURAL_SUFFIX_RE.test(translationKey)) {
      addReference(index, translationKey.replace(PLURAL_SUFFIX_RE, ''), translationKey);
      addReference(index, relativeKey.replace(PLURAL_SUFFIX_RE, ''), translationKey);
    }
  }

  return index;
}

function markStaticReference(reference, referenceIndex, usedKeys) {
  const matchingKeys = referenceIndex.get(reference);
  if (!matchingKeys) {
    return;
  }
  for (const key of matchingKeys) {
    usedKeys.add(key);
  }
}

function hasMeaningfulDynamicPrefix(prefix) {
  const relativePrefix = prefix.includes(':') ? prefix.slice(prefix.indexOf(':') + 1) : prefix;
  return relativePrefix.includes('.');
}

function scanSourceFile(file, referenceIndex, usedKeys, dynamicPrefixes) {
  const content = readFileSync(file, 'utf-8');

  for (const match of content.matchAll(STATIC_KEY_LITERAL_RE)) {
    markStaticReference(match.groups.key, referenceIndex, usedKeys);
  }

  for (const match of content.matchAll(DYNAMIC_TRANSLATION_PREFIX_RE)) {
    const { prefix } = match.groups;
    if (hasMeaningfulDynamicPrefix(prefix)) {
      dynamicPrefixes.add(prefix);
    }
  }
}

function applyDynamicPrefixes(translationKeys, dynamicPrefixes, usedKeys) {
  for (const translationKey of translationKeys) {
    const relativeKey = translationKey.slice(translationKey.indexOf(':') + 1);
    for (const prefix of dynamicPrefixes) {
      if (translationKey.startsWith(prefix) || relativeKey.startsWith(prefix)) {
        usedKeys.add(translationKey);
        break;
      }
    }
  }
}

function reportUnusedKeys(unusedKeys) {
  if (unusedKeys.length === 0) {
    success('No unused locale keys detected');
    return true;
  }

  error(`Found ${unusedKeys.length} unused locale keys:`);
  for (const key of unusedKeys) {
    warn(`  ${key}`);
  }
  return false;
}

/** Check for locale keys with no production source reference. */
export function checkUnusedKeys(locales, getAllFiles, srcDir) {
  const translationKeys = getTranslationKeys(locales);
  const referenceIndex = buildReferenceIndex(translationKeys);
  const usedKeys = new Set();
  const dynamicPrefixes = new Set();
  const files = getAllFiles(srcDir, SOURCE_FILE_RE);

  for (const file of files) {
    if (!EXCLUDED_FILES.some((excluded) => file.includes(excluded))) {
      scanSourceFile(file, referenceIndex, usedKeys, dynamicPrefixes);
    }
  }

  applyDynamicPrefixes(translationKeys, dynamicPrefixes, usedKeys);

  const unusedKeys = [...translationKeys]
    .filter((key) => !usedKeys.has(key))
    .sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  return reportUnusedKeys(unusedKeys);
}
