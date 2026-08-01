import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { JSX } from 'react';
import { FormProvider, useForm } from 'react-hook-form';
import { describe, expect, vi } from 'vitest';
import { PROFILE_FORM_DEFAULTS, type ProfileFormValues } from '../model/index.ts';
import { ExperienceCard } from './ExperienceCard.tsx';

vi.mock('react-i18next', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-i18next')>();
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string) =>
        ({
          'fields.experience.label': 'Experience',
          'fields.experience.description': 'Choose your experience preferences.',
          'fields.experience.yearsLabel': 'Years of experience',
          'fields.experience.decreaseYears': 'Decrease years of experience',
          'fields.experience.increaseYears': 'Increase years of experience',
          'fields.experience.seniorityLabel': 'Seniority levels',
        })[key] ?? key,
      i18n: { changeLanguage: vi.fn() },
    }),
  };
});

function ExperienceForm({
  onSubmit = vi.fn(),
}: {
  readonly onSubmit?: (values: ProfileFormValues) => void;
}): JSX.Element {
  const form = useForm<ProfileFormValues>({
    defaultValues: PROFILE_FORM_DEFAULTS,
  });

  return (
    <FormProvider {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)}>
        <ExperienceCard control={form.control} />
        <button type="submit">Save</button>
      </form>
    </FormProvider>
  );
}

function yearsInput(): HTMLInputElement {
  return screen.getByRole('spinbutton', { name: 'Years of experience' });
}

describe('ExperienceCard years control', () => {
  test('supports direct numeric entry and submits the existing numeric payload', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<ExperienceForm onSubmit={onSubmit} />);

    await user.clear(yearsInput());
    await user.type(yearsInput(), '12');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        experience_preference: expect.objectContaining({ experience_years: 12 }),
      }),
      expect.anything(),
    );
  });

  test('exposes labelled non-submit step buttons and changes by one', async () => {
    const user = userEvent.setup();
    render(<ExperienceForm />);
    const decrease = screen.getByRole('button', { name: 'Decrease years of experience' });
    const increase = screen.getByRole('button', { name: 'Increase years of experience' });

    expect(decrease).toHaveAttribute('type', 'button');
    expect(increase).toHaveAttribute('type', 'button');
    expect(decrease).toBeDisabled();

    await user.click(increase);
    expect(yearsInput()).toHaveValue(1);
    expect(decrease).toBeEnabled();
    await user.click(decrease);
    expect(yearsInput()).toHaveValue(0);
  });

  test('enforces both boundaries and disables the control that would cross them', async () => {
    const user = userEvent.setup();
    render(<ExperienceForm />);
    const input = yearsInput();
    const decrease = screen.getByRole('button', { name: 'Decrease years of experience' });
    const increase = screen.getByRole('button', { name: 'Increase years of experience' });

    await user.clear(input);
    await user.type(input, '50');
    expect(input).toHaveValue(50);
    expect(increase).toBeDisabled();
    await user.click(increase);
    expect(input).toHaveValue(50);

    await user.clear(input);
    await user.type(input, '0');
    expect(decrease).toBeDisabled();
  });

  test('supports ArrowUp and ArrowDown without exceeding the valid range', async () => {
    const user = userEvent.setup();
    render(<ExperienceForm />);
    const input = yearsInput();

    await user.clear(input);
    await user.type(input, '49');
    await user.type(input, '{ArrowUp}{ArrowUp}');
    expect(input).toHaveValue(50);
    await user.type(input, '{ArrowDown}');
    expect(input).toHaveValue(49);
  });

  test('exposes native range validation for typed values outside 0 through 50', async () => {
    const user = userEvent.setup();
    render(<ExperienceForm />);
    const input = yearsInput();

    await user.clear(input);
    await user.type(input, '51');

    expect(input).toHaveAttribute('min', '0');
    expect(input).toHaveAttribute('max', '50');
    expect(input).toBeInvalid();
    expect(input.validity.rangeOverflow).toBe(true);
  });

  test('requests a mobile numeric keyboard and suppresses native browser spinners', () => {
    render(<ExperienceForm />);
    const input = yearsInput();

    expect(input).toHaveAttribute('inputmode', 'numeric');
    expect(input).toHaveClass('[appearance:textfield]');
    expect(input).toHaveClass('[&::-webkit-inner-spin-button]:appearance-none');
    expect(input).toHaveClass('[&::-webkit-outer-spin-button]:appearance-none');
  });
});
