import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { JSONSchemaProperty } from '../../model/index.ts';
import { ADD_RE, renderArrayField } from './ArrayField.test-helpers.tsx';

const NO_ITEMS_ADDED_YET_RE = /no items added yet/iu;
const NO_ITEMS_YET_RE = /no items yet/iu;

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

const stringArraySchema: JSONSchemaProperty = {
  type: 'array',
  items: { type: 'string' },
};

describe('ArrayField - rendering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders empty state when no items exist', () => {
    renderArrayField(stringArraySchema);

    expect(screen.getByText(NO_ITEMS_ADDED_YET_RE)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: ADD_RE })).toBeInTheDocument();
  });

  test('renders the label', () => {
    renderArrayField(stringArraySchema, { label: 'Skills' });

    expect(screen.getByText('Skills')).toBeInTheDocument();
  });

  test('renders description tooltip when provided', () => {
    renderArrayField(stringArraySchema, {
      description: 'List your technical skills',
    });

    expect(screen.getByText('Items')).toBeInTheDocument();
  });

  test('renders items from default values', () => {
    renderArrayField(stringArraySchema, {
      defaultValues: { items: ['React', 'TypeScript'] },
    });

    expect(screen.queryByText(NO_ITEMS_YET_RE)).not.toBeInTheDocument();
  });
});

describe('ArrayField - add and remove', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('adds a new item when add button is clicked', async () => {
    const user = userEvent.setup();
    renderArrayField(stringArraySchema);

    await user.click(screen.getByRole('button', { name: ADD_RE }));

    expect(screen.queryByText(NO_ITEMS_ADDED_YET_RE)).not.toBeInTheDocument();
  });

  test('removes an item when remove button is clicked', async () => {
    const user = userEvent.setup();
    renderArrayField(stringArraySchema, {
      defaultValues: { items: ['React'] },
    });

    // Find remove buttons (Trash2 icon buttons)
    const allButtons = screen.getAllByRole('button');
    const removeButton = allButtons.find((btn) => btn.querySelector('.lucide-trash-2'));
    if (!removeButton) {
      throw new Error('Remove button not found');
    }

    await user.click(removeButton);

    expect(screen.getByText(NO_ITEMS_ADDED_YET_RE)).toBeInTheDocument();
  });
});

describe('ArrayField - number array', () => {
  const numberArraySchema: JSONSchemaProperty = {
    type: 'array',
    items: { type: 'number' },
  };

  test('renders number inputs for number-type items', () => {
    const SAMPLE_NUMBER_VALUE: number = 42;
    renderArrayField(numberArraySchema, {
      defaultValues: { items: [SAMPLE_NUMBER_VALUE] },
    });

    const inputs = screen.getAllByRole('spinbutton');
    expect(inputs.length).toBeGreaterThan(0);
  });
});

describe('ArrayField - textarea array', () => {
  const textareaArraySchema: JSONSchemaProperty = {
    type: 'array',
    items: {
      type: 'string',
      'x-widget': 'textarea',
    },
  };

  test('renders textarea for items with x-widget textarea', () => {
    renderArrayField(textareaArraySchema, {
      defaultValues: { items: ['Some text'] },
    });

    const textareas = screen.getAllByRole('textbox');
    expect(textareas.length).toBeGreaterThan(0);
  });
});

describe('ArrayField - object array', () => {
  const objectArraySchema: JSONSchemaProperty = {
    type: 'array',
    items: {
      type: 'object',
      properties: {
        title: { type: 'string', title: 'Title' },
        company: { type: 'string', title: 'Company' },
      },
    },
  };

  test('renders object fields for object-type items', () => {
    renderArrayField(objectArraySchema, {
      defaultValues: { items: [{ title: 'Engineer', company: 'Acme' }] },
    });

    expect(screen.getByTestId('object-fields')).toBeInTheDocument();
  });
});
