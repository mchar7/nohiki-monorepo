import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import type { FeatureImportanceRequest } from '@/shared/api/index.ts';
import { FeatureImportanceSettings } from './FeatureImportanceSettings.tsx';
import { FEATURE_IMPORTANCE_DEFAULTS } from './feature-importance-settings-model.ts';

const VALUES: FeatureImportanceRequest = {
  skill_match_importance: 80,
  location_importance: 50,
  work_arrangement_importance: 70,
  experience_importance: 60,
  salary_importance: 90,
  recency_importance: 40,
};

describe('FeatureImportanceSettings', () => {
  test('renders integer server values as their matching percentages', () => {
    render(<FeatureImportanceSettings values={VALUES} onChange={vi.fn()} />);

    expect(screen.getAllByText('80%')).toHaveLength(1);
    expect(screen.queryByText('8000%')).toBeNull();
    expect(screen.getAllByRole('slider')[0]).toHaveAttribute('aria-valuenow', '80');
  });

  test('configures sliders for integer percentages and emits integer values', () => {
    const onChange = vi.fn();
    render(<FeatureImportanceSettings values={VALUES} onChange={onChange} />);

    const [slider] = screen.getAllByRole('slider');
    if (!slider) throw new Error('expected a feature-importance slider');
    expect(slider).toHaveAttribute('aria-valuemin', '0');
    expect(slider).toHaveAttribute('aria-valuemax', '100');
    expect(slider).toHaveAttribute('aria-valuenow', '80');

    fireEvent.keyDown(slider, { key: 'ArrowRight' });
    expect(onChange).toHaveBeenCalledWith({ ...VALUES, skill_match_importance: 85 });
  });

  test('reset emits the neutral 50 default for every feature', () => {
    const onChange = vi.fn();
    render(<FeatureImportanceSettings values={VALUES} onChange={onChange} />);

    fireEvent.click(screen.getByRole('button', { name: /reset/iu }));
    expect(onChange).toHaveBeenCalledWith(FEATURE_IMPORTANCE_DEFAULTS);
    expect(Object.values(FEATURE_IMPORTANCE_DEFAULTS)).toEqual([50, 50, 50, 50, 50, 50]);
  });
});
