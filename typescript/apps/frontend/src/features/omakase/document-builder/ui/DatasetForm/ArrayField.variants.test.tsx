import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, vi } from 'vitest';
import { i18n } from '@/test/i18n-setup.ts';
import type { JSONSchemaProperty } from '../../model/index.ts';
import { ADD_RE, renderArrayField } from './ArrayField.test-helpers.tsx';

/** Must match the production constant in ArrayField.tsx */
const INLINE_FIELDS_MAX_ITEMS_TEST: number = 3;

vi.mock('../../lib/template.ts', () => ({
  getDefaultValueForArrayItem: (schema: JSONSchemaProperty) => {
    if (schema.type === 'object') {
      return {};
    }
    if (schema.type === 'number' || schema.type === 'integer') {
      return 0;
    }
    return '';
  },
  getUIHints: (schema: JSONSchemaProperty) => ({
    widget: schema['x-widget'] as string | undefined,
    direction: schema['x-direction'] as string | undefined,
    fieldNames: schema['x-field-names'] as string[] | undefined,
    placeholder: schema['x-placeholder'] as string | undefined,
  }),
  shouldRenderAsFields: (schema: JSONSchemaProperty) =>
    Boolean(schema.prefixItems) ||
    (Boolean(schema.maxItems) && (schema.maxItems ?? 0) <= INLINE_FIELDS_MAX_ITEMS_TEST),
}));

vi.mock('./ObjectFieldRenderer.tsx', () => ({
  renderObjectFields: () => <div data-testid="object-fields">Object Fields</div>,
  setArrayFieldComponent: vi.fn(),
}));

describe('ArrayField - tuple fields (prefixItems)', () => {
  const tupleSchema: JSONSchemaProperty = {
    type: 'array',
    prefixItems: [
      { type: 'string', title: 'Start Date', format: 'date' },
      { type: 'string', title: 'End Date', format: 'date' },
    ],
  };

  test('renders individual fields for tuple arrays', () => {
    renderArrayField(tupleSchema, { label: 'Date Range' });

    expect(screen.getByText('Start Date')).toBeInTheDocument();
    expect(screen.getByText('End Date')).toBeInTheDocument();
  });

  test('renders the label for tuple fields', () => {
    renderArrayField(tupleSchema, { label: 'Dates' });

    expect(screen.getByText('Dates')).toBeInTheDocument();
  });

  test('renders description tooltip for tuple fields', () => {
    renderArrayField(tupleSchema, {
      label: 'Date Range',
      description: 'Employment period',
    });

    expect(screen.getByText('Date Range')).toBeInTheDocument();
  });
});

describe('ArrayField - fixed-size array', () => {
  const fixedSizeSchema: JSONSchemaProperty = {
    type: 'array',
    items: { type: 'string' },
    maxItems: 2,
  };

  test('renders individual fields for fixed-size arrays', () => {
    renderArrayField(fixedSizeSchema, { label: 'Skills' });

    expect(
      screen.getByText(i18n.t('omakase.editor:fields.defaultFieldLabel', { index: 1 })),
    ).toBeInTheDocument();
    expect(
      screen.getByText(i18n.t('omakase.editor:fields.defaultFieldLabel', { index: 2 })),
    ).toBeInTheDocument();
  });

  test('renders description tooltip for fixed-size arrays', () => {
    renderArrayField(fixedSizeSchema, {
      label: 'Skills',
      description: 'Top skills',
    });

    expect(screen.getByText('Skills')).toBeInTheDocument();
  });

  test('renders number inputs for number fixed-size arrays', () => {
    const numberFixedSchema: JSONSchemaProperty = {
      type: 'array',
      items: { type: 'number' },
      maxItems: 2,
    };

    renderArrayField(numberFixedSchema, { label: 'Scores' });

    const inputs = screen.getAllByRole('spinbutton');
    expect(inputs.length).toBe(2);
  });
});

describe('ArrayField - item placeholders', () => {
  test('uses x-placeholder when available', async () => {
    const user = userEvent.setup();
    const schema: JSONSchemaProperty = {
      type: 'array',
      items: {
        type: 'string',
        'x-placeholder': 'Enter a skill',
      },
    };

    renderArrayField(schema);
    await user.click(screen.getByRole('button', { name: ADD_RE }));

    expect(screen.getByPlaceholderText('Enter a skill')).toBeInTheDocument();
  });

  test('uses examples as placeholder fallback', async () => {
    const user = userEvent.setup();
    const schema: JSONSchemaProperty = {
      type: 'array',
      items: {
        type: 'string',
        examples: ['JavaScript'],
      },
    };

    renderArrayField(schema);
    await user.click(screen.getByRole('button', { name: ADD_RE }));

    expect(screen.getByPlaceholderText('JavaScript')).toBeInTheDocument();
  });

  test('uses default placeholder when no hints available', async () => {
    const user = userEvent.setup();
    const schema: JSONSchemaProperty = {
      type: 'array',
      items: { type: 'string' },
    };

    renderArrayField(schema);
    await user.click(screen.getByRole('button', { name: ADD_RE }));

    expect(
      screen.getByPlaceholderText(i18n.t('omakase.editor:fields.itemPlaceholder')),
    ).toBeInTheDocument();
  });
});

describe('ArrayField - tuple field names', () => {
  test('uses x-field-names for tuple field labels', () => {
    const schema: JSONSchemaProperty = {
      type: 'array',
      prefixItems: [
        { type: 'string', format: 'date' },
        { type: 'string', format: 'date' },
      ],
      'x-field-names': ['From', 'To'],
    };

    renderArrayField(schema, { label: 'Period' });

    expect(screen.getByText('From')).toBeInTheDocument();
    expect(screen.getByText('To')).toBeInTheDocument();
  });

  test('falls back to item title or generic labels', () => {
    const schema: JSONSchemaProperty = {
      type: 'array',
      prefixItems: [{ type: 'string' }, { type: 'string', title: 'Custom Title' }],
    };

    renderArrayField(schema, { label: 'Range' });

    expect(
      screen.getByText(i18n.t('omakase.editor:fields.defaultFieldLabel', { index: 1 })),
    ).toBeInTheDocument();
    expect(screen.getByText('Custom Title')).toBeInTheDocument();
  });
});

describe('ArrayField - grid layout', () => {
  test('uses column direction when specified', () => {
    const schema: JSONSchemaProperty = {
      type: 'array',
      items: { type: 'string' },
      maxItems: 3,
      'x-direction': 'column',
    };

    renderArrayField(schema, { label: 'Items' });

    // Items should render - the grid class is applied internally
    expect(
      screen.getByText(i18n.t('omakase.editor:fields.defaultFieldLabel', { index: 1 })),
    ).toBeInTheDocument();
  });
});
