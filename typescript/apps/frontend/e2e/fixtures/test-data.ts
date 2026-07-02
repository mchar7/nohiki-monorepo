import { TEST_DATA, TEST_USER } from '../constants.ts';

const DEFAULT_PROFILE_KEYWORD_COUNT = 3;

export const TestData = {
  users: {
    primary: {
      email: TEST_USER.email,
      password: TEST_USER.password,
    },
    secondary: {
      email: 'e2e-secondary@nohiki.test',
      password: 'SecondaryP@ss123!',
    },
  },

  profiles: {
    default: {
      name: 'E2E Test Profile',
      keywords: TEST_DATA.skills.allowed.slice(0, DEFAULT_PROFILE_KEYWORD_COUNT),
    },
  },

  generateUniqueName: (prefix: string): string => `${prefix}-${Date.now()}`,

  generateUniqueEmail: (prefix: string): string => `${prefix}-${Date.now()}@example.com`,
} as const;
