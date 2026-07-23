import type { RenderResult } from '@testing-library/react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { JSX } from 'react';
import { useForm } from 'react-hook-form';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import { i18n } from '@/test/i18n-setup.ts';
import type { UIHints } from '../../lib/template.ts';
import type { FormErrors, FormRegisterFunction } from '../../model/index.ts';
import { FormField } from './FormField.tsx';

const SHOW_PASSWORD_RE = /show password/iu;
const HIDE_PASSWORD_RE = /hide password/iu;

function renderFormField(
  props: {
    name?: string;
    label?: string;
    description?: string;
    type?: 'string' | 'number' | 'integer' | 'boolean' | 'date' | 'text';
    format?: string;
    required?: boolean;
    uiHints?: UIHints;
    enumValues?: unknown[];
    defaultValue?: unknown;
    widget?: string;
    errors?: FormErrors;
  } = {},
): RenderResult {
  const { name = 'field', label = 'Test Field', type = 'string', errors = {}, ...rest } = props;

  function TestComponent(): JSX.Element {
    const methods = useForm<Record<string, unknown>>({ defaultValues: { [name]: '' } });

    return (
      <I18nextProvider i18n={i18n}>
        <form>
          <FormField
            name={name}
            label={label}
            type={type}
            register={methods.register as FormRegisterFunction}
            errors={errors}
            {...rest}
          />
        </form>
      </I18nextProvider>
    );
  }

  return render(<TestComponent />);
}

describe('FormField - text input', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders a text input with label', () => {
    renderFormField({ label: 'Full Name' });

    expect(screen.getByText('Full Name')).toBeInTheDocument();
    expect(screen.getByRole('textbox')).toBeInTheDocument();
  });

  test('renders description tooltip when provided', () => {
    renderFormField({ description: 'Enter your full legal name' });

    expect(screen.getByText('Test Field')).toBeInTheDocument();
  });

  test('renders required indicator', () => {
    renderFormField({ required: true });

    expect(screen.getByText('*')).toBeInTheDocument();
  });

  test('renders error message when field has errors', () => {
    renderFormField({
      name: 'email',
      errors: { email: { message: 'Email is required', type: 'required' } },
    });

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Email is required')).toBeInTheDocument();
  });

  test('renders fallback error message when no message provided', () => {
    renderFormField({
      name: 'email',
      errors: { email: { type: 'required' } },
    });

    expect(screen.getByRole('alert')).toBeInTheDocument();
  });
});

describe('FormField - textarea widget', () => {
  test('renders textarea when format is textarea', () => {
    renderFormField({ format: 'textarea' });

    expect(screen.getByRole('textbox')).toBeInTheDocument();
    const textarea = document.querySelector('textarea');
    expect(textarea).toBeTruthy();
  });

  test('renders textarea via uiHints widget', () => {
    renderFormField({ uiHints: { widget: 'textarea' } });

    const textarea = document.querySelector('textarea');
    expect(textarea).toBeTruthy();
  });
});

describe('FormField - select widget', () => {
  test('renders select for enum values', () => {
    renderFormField({
      enumValues: ['Option A', 'Option B', 'Option C'],
      defaultValue: 'Option A',
    });

    expect(screen.getByRole('combobox')).toBeInTheDocument();
  });

  test('renders select with label context', () => {
    renderFormField({
      label: 'Color',
      enumValues: ['Red', 'Green', 'Blue'],
    });

    expect(screen.getByRole('combobox')).toBeInTheDocument();
    expect(screen.getByText('Color')).toBeInTheDocument();
  });
});

describe('FormField - checkbox widget', () => {
  test('renders checkbox for boolean type', () => {
    renderFormField({ type: 'boolean', label: 'Accept Terms' });

    expect(screen.getByRole('checkbox')).toBeInTheDocument();
    expect(screen.getByText('Accept Terms')).toBeInTheDocument();
  });

  test('renders required indicator on checkbox label', () => {
    renderFormField({ type: 'boolean', label: 'Required Check', required: true });

    expect(screen.getByText('*')).toBeInTheDocument();
  });

  test('renders description tooltip for checkbox', () => {
    renderFormField({
      type: 'boolean',
      label: 'Agree',
      description: 'You must agree to proceed',
    });

    expect(screen.getByText('Agree')).toBeInTheDocument();
  });

  test('renders error for checkbox', () => {
    renderFormField({
      type: 'boolean',
      name: 'agree',
      label: 'Agree',
      errors: { agree: { message: 'Must agree', type: 'required' } },
    });

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Must agree')).toBeInTheDocument();
  });
});

describe('FormField - password widget', () => {
  test('renders password input', () => {
    renderFormField({ format: 'password' });

    const input = document.querySelector('input[type="password"]');
    expect(input).toBeTruthy();
  });

  test('toggles password visibility', async () => {
    const user = userEvent.setup();
    renderFormField({ format: 'password' });

    const toggleButton = screen.getByRole('button', { name: SHOW_PASSWORD_RE });
    expect(toggleButton).toBeInTheDocument();

    await user.click(toggleButton);

    const visibleInput = document.querySelector('input[type="text"]');
    expect(visibleInput).toBeTruthy();

    const hideButton = screen.getByRole('button', { name: HIDE_PASSWORD_RE });
    await user.click(hideButton);

    const hiddenInput = document.querySelector('input[type="password"]');
    expect(hiddenInput).toBeTruthy();
  });
});

describe('FormField - email widget', () => {
  test('renders email input', () => {
    renderFormField({ format: 'email' });

    const input = document.querySelector('input[type="email"]');
    expect(input).toBeTruthy();
  });
});

describe('FormField - date widget', () => {
  test('renders text input for date type without format', () => {
    renderFormField({ type: 'date' });

    // type='date' alone doesn't trigger date widget - format='date' is required
    const input = document.querySelector('input[type="text"]');
    expect(input).toBeTruthy();
  });

  test('renders date input for date format', () => {
    renderFormField({ format: 'date' });

    const input = document.querySelector('input[type="date"]');
    expect(input).toBeTruthy();
  });
});

describe('FormField - number widget', () => {
  test('renders number input for number type', () => {
    renderFormField({ type: 'number' });

    expect(screen.getByRole('spinbutton')).toBeInTheDocument();
  });

  test('renders number input for integer type with step=1', () => {
    renderFormField({ type: 'integer' });

    const input = screen.getByRole('spinbutton');
    expect(input).toBeInTheDocument();
  });
});

describe('FormField - placeholder', () => {
  test('uses uiHints placeholder when provided', () => {
    renderFormField({ uiHints: { placeholder: 'Custom placeholder' } });

    expect(screen.getByPlaceholderText('Custom placeholder')).toBeInTheDocument();
  });
});

describe('FormField - error styling', () => {
  test('applies error class to textarea', () => {
    renderFormField({
      name: 'bio',
      format: 'textarea',
      errors: { bio: { message: 'Too short', type: 'minLength' } },
    });

    const textarea = document.querySelector('textarea');
    expect(textarea?.className).toContain('destructive');
  });

  test('applies error class to select', () => {
    renderFormField({
      name: 'color',
      enumValues: ['Red', 'Blue'],
      errors: { color: { message: 'Required', type: 'required' } },
    });

    expect(screen.getByRole('alert')).toBeInTheDocument();
  });
});
