import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';

const PROFILES_ID_RE = /\/profiles\/(?<profileId>[\w-]+)/u;
const MORE_MENU_RE = /more/iu;
const DELETE_MENU_ITEM_RE = /delete/iu;
const CONFIRM_YES_DELETE_RE = /confirm|yes|delete/iu;

/** Extract the profile ID from the profile link on the profiles list page. */
export async function extractProfileId(page: Page, profileName: string): Promise<string> {
  const profileLink = page.getByRole('link', { name: new RegExp(profileName, 'u') });
  const href = await profileLink.getAttribute('href');
  const match = PROFILES_ID_RE.exec(href ?? '');
  expect(match).toBeTruthy();
  return match?.groups?.profileId ?? '';
}

/** Delete the currently displayed profile via the actions dropdown and confirm the modal. */
export async function deleteCurrentProfile(page: Page): Promise<void> {
  // Open the actions dropdown menu
  await page.getByRole('button', { name: MORE_MENU_RE }).click();
  await page.getByRole('menuitem', { name: DELETE_MENU_ITEM_RE }).click();
  await page.getByRole('button', { name: CONFIRM_YES_DELETE_RE }).click();
}
