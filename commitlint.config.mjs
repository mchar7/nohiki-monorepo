/**
 * Commitlint configuration for Nohiki Monorepo
 *
 * Enforces conventional commit format:
 *   type(scope?): subject
 *
 * Allowed types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert
 *
 * Examples:
 *   feat: add user authentication
 *   fix(auth): resolve token refresh issue
 *   docs: update API documentation
 *   refactor(kafka): simplify message handler
 */
export default {
  extends: ['@commitlint/config-conventional'],
  // Classic "Merge pull request" subjects must fail, not silently pass.
  defaultIgnores: false,
  // Integration merge subjects are not author-controllable.
  ignores: [(message) => /^Merge (remote-tracking )?branch '.+' into .+/.test(message)],
  rules: {
    // Allowed commit types
    'type-enum': [
      2,
      'always',
      [
        'feat', // New feature
        'fix', // Bug fix
        'docs', // Documentation only
        'style', // Code style (formatting, semicolons, etc.)
        'refactor', // Code refactoring (no feature/fix)
        'perf', // Performance improvement
        'test', // Adding/updating tests
        'build', // Build system or dependencies
        'ci', // CI/CD configuration
        'chore', // Maintenance tasks
        'revert', // Revert previous commit
      ],
    ],

    // Subject line rules
    'subject-case': [
      2,
      'never',
      [
        'sentence-case', // No "Add a new feature"
        'start-case', // No "Add New Feature"
        'pascal-case', // No "AddNewFeature"
        'upper-case', // No "ADD NEW FEATURE"
      ],
    ],

    // Scope is a service or library name
    'scope-case': [2, 'always', 'kebab-case'],

    // Spec items 6 and 8: body and footer start one blank line after the
    // preceding section; config-conventional only warns.
    'body-leading-blank': [2, 'always'],
    'footer-leading-blank': [2, 'always'],

    // Header max length (type + scope + subject)
    'header-max-length': [2, 'always', 100],

    // Allow long lines in body (for URLs, logs, etc.)
    'body-max-line-length': [0, 'always', Infinity],

    // Footer max line length (for issue references)
    'footer-max-line-length': [0, 'always', Infinity],
  },
};
