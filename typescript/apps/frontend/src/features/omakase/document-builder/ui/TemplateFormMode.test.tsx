import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';
import { nonNull } from '@/shared/test-utils';
import { i18n } from '@/test/setup.ts';
import type { ContentSchema, FieldDescriptor } from '../lib/TemplateFormModeModel.ts';
import { flattenSchema } from '../lib/TemplateFormModeModel.ts';
import { TemplateFormMode } from './TemplateFormMode.tsx';

const SAMPLE_AGE: number = 30;

function renderWithI18n(ui: React.ReactElement): ReturnType<typeof render> {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>);
}

describe('flattenSchema - basic flattening', () => {
  test('flattens a simple flat schema into field descriptors', () => {
    const schema: ContentSchema = {
      name: { type: 'string' },
      age: { type: 'number' },
    };

    const fields = flattenSchema(schema, '');

    expect(fields).toEqual<FieldDescriptor[]>([
      { path: 'name', label: 'Name', description: undefined, fieldType: 'text' },
      { path: 'age', label: 'Age', description: undefined, fieldType: 'number' },
    ]);
  });

  test('flattens nested object schemas with dot-path notation', () => {
    const schema: ContentSchema = {
      contact: {
        type: 'object',
        properties: {
          email: { type: 'string' },
          phone: { type: 'string' },
        },
      },
    };

    const fields = flattenSchema(schema, '');

    expect(fields).toEqual<FieldDescriptor[]>([
      { path: 'contact.email', label: 'Email', description: undefined, fieldType: 'text' },
      { path: 'contact.phone', label: 'Phone', description: undefined, fieldType: 'text' },
    ]);
  });

  test('handles deeply nested objects', () => {
    const schema: ContentSchema = {
      person: {
        type: 'object',
        properties: {
          address: {
            type: 'object',
            properties: {
              city: { type: 'string' },
            },
          },
        },
      },
    };

    const fields = flattenSchema(schema, '');

    expect(fields).toHaveLength(1);
    expect(nonNull(fields[0]).path).toBe('person.address.city');
  });
});

describe('flattenSchema - field type inference', () => {
  test('infers textarea for keys containing description/summary/body', () => {
    const schema: ContentSchema = {
      job_description: { type: 'string' },
      summary: { type: 'string' },
      body: { type: 'string' },
    };

    const fields = flattenSchema(schema, '');

    expect(nonNull(fields[0]).fieldType).toBe('textarea');
    expect(nonNull(fields[1]).fieldType).toBe('textarea');
    expect(nonNull(fields[2]).fieldType).toBe('textarea');
  });

  test('infers number type for integer entries', () => {
    const schema: ContentSchema = {
      count: { type: 'integer' },
    };

    const fields = flattenSchema(schema, '');

    expect(nonNull(fields[0]).fieldType).toBe('number');
  });
});

describe('flattenSchema - labels and descriptions', () => {
  test('preserves descriptions from schema entries', () => {
    const schema: ContentSchema = {
      title: { type: 'string', description: 'Your job title' },
    };

    const fields = flattenSchema(schema, '');

    expect(nonNull(fields[0]).description).toBe('Your job title');
  });

  test('humanizes underscore-separated keys', () => {
    const schema: ContentSchema = {
      full_name: { type: 'string' },
      professional_title: { type: 'string' },
    };

    const fields = flattenSchema(schema, '');

    expect(nonNull(fields[0]).label).toBe('Full Name');
    expect(nonNull(fields[1]).label).toBe('Professional Title');
  });
});

describe('TemplateFormMode - rendering', () => {
  const sampleSchema: ContentSchema = {
    full_name: { type: 'string' },
    age: { type: 'number' },
    bio: { type: 'string' },
  };

  const sampleData = {
    full_name: 'Jane Doe',
    age: SAMPLE_AGE,
    bio: 'A developer',
  };

  test('renders labeled input fields for each schema key', () => {
    renderWithI18n(
      <TemplateFormMode contentSchema={sampleSchema} data={sampleData} onDataChange={vi.fn()} />,
    );

    expect(screen.getByLabelText('Full Name')).toBeInTheDocument();
    expect(screen.getByLabelText('Age')).toBeInTheDocument();
    expect(screen.getByLabelText('Bio')).toBeInTheDocument();
  });

  test('renders text input for string fields and number input for number fields', () => {
    renderWithI18n(
      <TemplateFormMode contentSchema={sampleSchema} data={sampleData} onDataChange={vi.fn()} />,
    );

    const nameInput = screen.getByLabelText('Full Name');
    expect(nameInput).toHaveAttribute('type', 'text');

    const ageInput = screen.getByLabelText('Age');
    expect(ageInput).toHaveAttribute('type', 'number');
  });

  test('renders textarea for keys that match textarea keywords', () => {
    renderWithI18n(
      <TemplateFormMode contentSchema={sampleSchema} data={sampleData} onDataChange={vi.fn()} />,
    );

    const bioField = screen.getByLabelText('Bio');
    expect(bioField.tagName).toBe('TEXTAREA');
  });

  test('renders the panel header with translated label', () => {
    renderWithI18n(
      <TemplateFormMode contentSchema={sampleSchema} data={sampleData} onDataChange={vi.fn()} />,
    );

    expect(screen.getByText('Form Fields')).toBeInTheDocument();
  });
});

describe('TemplateFormMode - data handling', () => {
  const sampleSchema: ContentSchema = {
    full_name: { type: 'string' },
    age: { type: 'number' },
  };

  const sampleData = {
    full_name: 'Jane Doe',
    age: SAMPLE_AGE,
  };

  test('populates fields with existing data values', () => {
    renderWithI18n(
      <TemplateFormMode contentSchema={sampleSchema} data={sampleData} onDataChange={vi.fn()} />,
    );

    expect(screen.getByLabelText('Full Name')).toHaveValue('Jane Doe');
    expect(screen.getByLabelText('Age')).toHaveValue(SAMPLE_AGE);
  });

  test('calls onDataChange when a field value changes', async () => {
    const onDataChange = vi.fn();
    const user = userEvent.setup();

    renderWithI18n(
      <TemplateFormMode
        contentSchema={sampleSchema}
        data={sampleData}
        onDataChange={onDataChange}
      />,
    );

    const nameInput = screen.getByLabelText('Full Name');
    await user.type(nameInput, 'X');

    expect(onDataChange).toHaveBeenCalled();
    const [firstCallArgs] = onDataChange.mock.calls;
    const { full_name, age } = nonNull(firstCallArgs)[0];
    expect(full_name).toBe('Jane DoeX');
    expect(age).toBe(SAMPLE_AGE);
  });
});

describe('TemplateFormMode - nested objects', () => {
  test('renders nested object fields with correct values', () => {
    const nestedSchema: ContentSchema = {
      contact: {
        type: 'object',
        properties: {
          email: { type: 'string' },
        },
      },
    };
    const nestedData = { contact: { email: 'test@example.com' } };

    renderWithI18n(
      <TemplateFormMode contentSchema={nestedSchema} data={nestedData} onDataChange={vi.fn()} />,
    );

    expect(screen.getByLabelText('Email')).toHaveValue('test@example.com');
  });
});
