#!/usr/bin/env node
/**
 * i18n Check Script
 *
 * Validates:
 * 1. No hardcoded user-facing strings in source code
 * 2. All locale files have matching keys between languages
 * 3. No unused locale keys
 * 4. 100% localization coverage
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import { checkLocaleConsistency } from './i18n/compare.mjs';
import { error, success } from './i18n/report.mjs';
import { checkHardcodedStrings, checkUnusedKeys } from './i18n/scan.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = join(__dirname, '..');
const LOCALES_DIR = join(ROOT_DIR, 'public', 'locales');
const SRC_DIR = join(ROOT_DIR, 'src');

const EXIT_SUCCESS = 0;
const EXIT_FAILURE = 1;

/** Get all files recursively matching a pattern. */
function getAllFiles(dir, pattern) {
  const files = [];
  const items = readdirSync(dir);

  for (const item of items) {
    const fullPath = join(dir, item);
    const stat = statSync(fullPath);

    if (stat.isDirectory()) {
      files.push(...getAllFiles(fullPath, pattern));
    } else if (pattern.test(fullPath)) {
      files.push(fullPath);
    }
  }

  return files;
}

/** Load all locale JSON files from the locales directory. */
function loadLocales() {
  const locales = {};
  const localeDirs = readdirSync(LOCALES_DIR);

  for (const locale of localeDirs) {
    const localePath = join(LOCALES_DIR, locale);
    const files = readdirSync(localePath).filter((f) => f.endsWith('.json'));

    locales[locale] = {};
    for (const file of files) {
      const filePath = join(localePath, file);
      const content = readFileSync(filePath, 'utf-8');
      locales[locale][file] = JSON.parse(content);
    }
  }

  return locales;
}

function main() {
  const locales = loadLocales();

  let allPassed = true;
  allPassed = checkLocaleConsistency(locales) && allPassed;
  allPassed = checkHardcodedStrings(getAllFiles, SRC_DIR, ROOT_DIR) && allPassed;
  allPassed = checkUnusedKeys(locales, getAllFiles, SRC_DIR) && allPassed;
  if (allPassed) {
    success('All i18n checks passed!');
    process.exit(EXIT_SUCCESS);
  } else {
    error('Some i18n checks failed');
    process.exit(EXIT_FAILURE);
  }
}

main();
