# Playwright E2E Tests

Browser-based end-to-end tests that exercise the frontend through Playwright.

## Quick Start

```bash
# Install workspace dependencies from the repository root
pnpm install

# Install Playwright browsers
pnpm --filter nohiki-frontend exec playwright install

# Run all tests
just test-e2e

# Run with UI (interactive)
just test-e2e-ui

# Run a specific journey
just test-e2e-journey profile-management
```

## Directory Structure

```text
e2e/
├── playwright.config.ts    # Projects, reporters, web server, and browser settings
├── global-setup.ts         # Creates a unique test user and saves browser state
├── constants.ts            # Shared paths, credentials, selectors, and timeouts
├── fixtures/               # Test data
├── pages/                  # Page Object Models
├── journeys/               # Browser journeys
└── utils/                  # Auth, API, page, and journey helpers
```

## Writing Tests

### Page Object Pattern

```typescript
import { ProfilesPage } from '../pages';

test('example', async ({ page }) => {
  const profilesPage = new ProfilesPage(page);
  await profilesPage.goto();
  await profilesPage.clickCreateProfile();
});
```

### Sequential Journeys

Use `test.describe.serial()` for tests that share state:

```typescript
test.describe.serial('My Journey', () => {
  let sharedData: string;

  test('1. First step', async ({ page }) => {
    sharedData = 'created in step 1';
  });

  test('2. Second step uses shared data', async ({ page }) => {
    // sharedData is available here
  });
});
```

### Handling CQRS Delays

After creating entities, wait for projections:

```typescript
await expect(
  page.getByText('New Profile Name')
).toBeVisible({ timeout: 30_000 });
```

## Auth Strategy

- `global-setup.ts` registers and logs in a unique primary user for each run
- Setup writes its browser state to `e2e/.output/auth/primary-user.json`
- The normal Chromium project depends on setup and clones that state into each test context
- Tests that create or exercise another user explicitly override storage with `{ cookies: [], origins: [] }`
- The feature-on auth-listings lane runs independently, without setup or the primary-user state

## Debugging

```bash
# Headed mode (see browser)
npx playwright test --headed

# Debug mode (step through)
npx playwright test --debug

# UI mode (interactive)
npx playwright test --ui

# Trace on (for failure analysis)
npx playwright test --trace on
```

## Reports

```bash
# Generate HTML report
npx playwright test --reporter=html

# View report
npx playwright show-report
```

## CI Integration

Tests run automatically via GitHub Actions. Playwright selects list, HTML, and GitHub reporters
in CI, starts the Vite development server, runs the setup project, then runs Chromium journeys.
It retains HTML output, traces, screenshots, and video according to the workflow and Playwright
configuration.

## Primary Test User State

`global-setup.ts` creates `e2e-<timestamp>@example.com` with the password from
`e2e/constants.ts`, then writes the authenticated browser state to
`e2e/.output/auth/primary-user.json`. The ignored state file is replaced on the next setup run.
No fixed email or browser context is reused across runs.

## Justfile Commands

```bash
# Run all E2E tests
just test-e2e

# Interactive UI mode
just test-e2e-ui

# Debug mode
just test-e2e-debug

# Specific journey
just test-e2e-journey profile-management

# Show report
just test-e2e-report

# Headed mode
just test-e2e-headed
```

## Adding New Tests

1. Add journey file in `journeys/`
2. Use Page Object Models from `pages/`
3. Use `test.describe.serial()` for stateful journeys
4. Handle CQRS delays with appropriate timeouts
5. Follow naming convention: `<feature>.spec.ts`

## Page Object Guidelines

1. Extend `BasePage` for common functionality
2. Define locators as class properties
3. Create methods for common actions
4. Use `data-testid` attributes for reliable selectors
