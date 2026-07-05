/**
 * Terminal output helpers for i18n validation reporting.
 */

const RED = '\x1b[31m';
const GREEN = '\x1b[32m';
const YELLOW = '\x1b[33m';
const RESET = '\x1b[0m';

export function error(msg) {
  console.error(`${RED}✗ ${msg}${RESET}`);
}

export function success(msg) {
  console.log(`${GREEN}✓ ${msg}${RESET}`);
}

export function warn(msg) {
  console.warn(`${YELLOW}⚠ ${msg}${RESET}`);
}
