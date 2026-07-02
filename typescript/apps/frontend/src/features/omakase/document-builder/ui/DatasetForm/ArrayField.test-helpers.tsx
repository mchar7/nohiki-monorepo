/**
 * Shared test setup for ArrayField test suites.
 *
 * vi.mock() calls must remain in each test file (hoisted by Vitest)
 * with inline factory implementations. This module provides the
 * render helper, constants, and regex patterns used across both suites.
 */
import type { RenderResult } from '@testing-library/react';
import { render } from '@testing-library/react';
import type { JSX } from 'react';
import { useForm } from 'react-hook-form';
import { I18nextProvider } from 'react-i18next';
import { i18n } from '@/test/setup.ts';
import type { FormErrors, FormRegisterFunction, JSONSchemaProperty } from '../../model/index.ts';
import { ArrayField } from './ArrayField.tsx';

interface RenderArrayFieldProps {
  name?: string;
  label?: string;
  description?: string;
  defaultValues?: Record<string, unknown>;
}

export const ADD_RE = /add/iu;

/**
 * Renders an ArrayField inside a react-hook-form context with i18n provider.
 */
export function renderArrayField(
  schema: JSONSchemaProperty,
  props: RenderArrayFieldProps = {},
): RenderResult {
  const { name = 'items', label = 'Items', description, defaultValues } = props;

  function TestComponent(): JSX.Element {
    const methods = useForm<Record<string, unknown>>({
      defaultValues: defaultValues ?? { [name]: [] },
    });

    return (
      <I18nextProvider i18n={i18n}>
        <form>
          <ArrayField
            name={name}
            label={label}
            description={description}
            schema={schema}
            register={methods.register as FormRegisterFunction}
            control={methods.control}
            errors={methods.formState.errors as FormErrors}
          />
        </form>
      </I18nextProvider>
    );
  }

  return render(<TestComponent />);
}
