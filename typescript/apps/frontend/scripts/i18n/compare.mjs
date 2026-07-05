/**
 * Locale comparison logic for i18n validation.
 *
 * Checks consistency between locale files: missing/extra files and key mismatches.
 */

import { error, success, warn } from './report.mjs';

/** Get all nested keys from a locale JSON object. */
function getAllKeys(obj, prefix = '') {
  const keys = [];
  for (const key of Object.keys(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (typeof obj[key] === 'object' && obj[key] !== null && !Array.isArray(obj[key])) {
      keys.push(...getAllKeys(obj[key], fullKey));
    } else {
      keys.push(fullKey);
    }
  }
  return keys;
}

function checkMissingFiles(referenceFiles, files, locale) {
  let hasErrors = false;
  for (const file of referenceFiles) {
    if (!files.includes(file)) {
      error(`Missing file in ${locale}: ${file}`);
      hasErrors = true;
    }
  }
  return hasErrors;
}

function checkExtraFiles(files, referenceFiles, locale, referenceLocale) {
  for (const file of files) {
    if (!referenceFiles.includes(file)) {
      warn(`Extra file in ${locale}: ${file} (not in ${referenceLocale})`);
    }
  }
}

/** @param {{ locales: Record<string, any>, referenceLocale: string, locale: string, referenceFiles: string[], files: string[] }} opts */
function checkKeyMismatches({ locales, referenceLocale, locale, referenceFiles, files }) {
  let hasErrors = false;
  for (const file of referenceFiles.filter((f) => files.includes(f))) {
    const refKeys = getAllKeys(locales[referenceLocale][file]).sort();
    const localeKeys = getAllKeys(locales[locale][file]).sort();

    const missingInLocale = refKeys.filter((k) => !localeKeys.includes(k));
    const extraInLocale = localeKeys.filter((k) => !refKeys.includes(k));

    if (missingInLocale.length > 0) {
      error(`${locale}/${file}: Missing keys: ${missingInLocale.join(', ')}`);
      hasErrors = true;
    }

    if (extraInLocale.length > 0) {
      warn(
        `${locale}/${file}: Extra keys (not in ${referenceLocale}): ${extraInLocale.join(', ')}`,
      );
    }
  }
  return hasErrors;
}

/** Check locale consistency between languages. */
function checkLocaleConsistency(locales) {
  const localeNames = Object.keys(locales);
  if (localeNames.length < 2) {
    success('Only one locale found, skipping consistency check');
    return true;
  }

  const [referenceLocale] = localeNames;
  const referenceFiles = Object.keys(locales[referenceLocale]);
  let hasErrors = false;

  for (const locale of localeNames.slice(1)) {
    const files = Object.keys(locales[locale]);
    hasErrors = checkMissingFiles(referenceFiles, files, locale) || hasErrors;
    checkExtraFiles(files, referenceFiles, locale, referenceLocale);
    hasErrors =
      checkKeyMismatches({ locales, referenceLocale, locale, referenceFiles, files }) || hasErrors;
  }

  if (!hasErrors) {
    success(`All ${localeNames.length} locales are consistent`);
  }

  return !hasErrors;
}

export { checkLocaleConsistency, getAllKeys };
