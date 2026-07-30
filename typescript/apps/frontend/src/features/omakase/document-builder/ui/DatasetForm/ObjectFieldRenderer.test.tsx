import { render, screen } from '@testing-library/react';
import type { JSX } from 'react';
import { useForm } from 'react-hook-form';
import { I18nextProvider } from 'react-i18next';
import { expect, test } from 'vitest';
import { i18n } from '@/test/i18n-setup.ts';
import type { FormErrors, FormRegisterFunction, JSONSchemaProperty } from '../../model/index.ts';
import { renderObjectFields } from './ObjectFieldRenderer.tsx';

const nestedSchema: JSONSchemaProperty = {
  type: 'object',
  properties: {
    profile: {
      type: 'object',
      title: 'Profile',
      properties: {
        experience: {
          type: 'array',
          title: 'Experience',
          items: {
            type: 'object',
            properties: {
              employer: {
                type: 'object',
                title: 'Employer',
                properties: {
                  name: { type: 'string', title: 'Employer Name' },
                },
              },
            },
          },
        },
      },
    },
  },
};

test('renders object fields nested through an array item object', () => {
  function NestedObjectForm(): JSX.Element {
    const form = useForm<Record<string, unknown>>({
      defaultValues: {
        profile: {
          experience: [{ employer: { name: 'Acme Corp' } }],
        },
      },
    });

    return (
      <I18nextProvider i18n={i18n}>
        <form>
          {renderObjectFields({
            baseName: '',
            schema: nestedSchema,
            register: form.register as FormRegisterFunction,
            control: form.control,
            errors: form.formState.errors as FormErrors,
          })}
        </form>
      </I18nextProvider>
    );
  }

  render(<NestedObjectForm />);

  expect(screen.getByText('Profile')).toBeInTheDocument();
  expect(screen.getByText('Experience')).toBeInTheDocument();
  expect(screen.getByText('Employer')).toBeInTheDocument();
  expect(screen.getByText('Employer Name')).toBeInTheDocument();
  expect(screen.getByRole('textbox')).toHaveAttribute('name', 'profile.experience.0.employer.name');
  expect(screen.getByRole('textbox')).toHaveValue('Acme Corp');
});
