import { render } from '@testing-library/react';
import { describe, expect } from 'vitest';
import { configureAxe } from 'vitest-axe';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './select.tsx';

describe('Select - accessibility', () => {
  test('has no accessibility violations', async () => {
    // Disable region rule: component tests render in isolation without landmarks
    const isolatedAxe = configureAxe({ rules: { region: { enabled: false } } });
    const { container } = render(
      <Select defaultValue="a">
        <SelectTrigger aria-label="test select">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="a">Option A</SelectItem>
          <SelectItem value="b">Option B</SelectItem>
        </SelectContent>
      </Select>,
    );
    const results = await isolatedAxe(container);
    expect(results).toHaveNoViolations();
  });
});
