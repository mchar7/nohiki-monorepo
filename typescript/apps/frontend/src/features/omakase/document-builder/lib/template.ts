interface UIHints {
  direction?: 'row' | 'column';
  fieldNames?: string[];
  placeholder?: string;
  widget?: string;
  columns?: number;
  showItemLabels?: boolean;
  renderAsFields?: boolean;
}

const UI_HINT_KEYS: Array<{ schemaKey: string; hintKey: keyof UIHints }> = [
  { schemaKey: 'x-direction', hintKey: 'direction' },
  { schemaKey: 'x-field-names', hintKey: 'fieldNames' },
  { schemaKey: 'x-placeholder', hintKey: 'placeholder' },
  { schemaKey: 'x-widget', hintKey: 'widget' },
  { schemaKey: 'x-columns', hintKey: 'columns' },
  { schemaKey: 'x-show-item-labels', hintKey: 'showItemLabels' },
  { schemaKey: 'x-render-as-fields', hintKey: 'renderAsFields' },
];

function getUIHints(schema: Record<string, unknown> | object): UIHints {
  const schemaObj = schema as Record<string, unknown>;
  const hints: UIHints = {};

  for (const { schemaKey, hintKey } of UI_HINT_KEYS) {
    if (schemaObj[schemaKey] !== undefined) {
      (hints as Record<string, unknown>)[hintKey] = schemaObj[schemaKey];
    }
  }

  return hints;
}

// Arrays with 3 or fewer items are rendered as individual fields rather than a list
const MAX_ITEMS_FOR_FIELD_RENDERING: number = 3;

function shouldRenderAsFields(schema: Record<string, unknown> | object): boolean {
  const schemaObj = schema as Record<string, unknown>;
  if (schemaObj.prefixItems) {
    return true;
  }

  const maxItems = schemaObj.maxItems as number | undefined;
  if (maxItems && maxItems <= MAX_ITEMS_FOR_FIELD_RENDERING) {
    return true;
  }

  return false;
}

export type { UIHints };
export { getUIHints, shouldRenderAsFields };
