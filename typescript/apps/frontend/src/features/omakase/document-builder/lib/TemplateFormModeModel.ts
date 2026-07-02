type ContentSchema = Record<string, ContentSchemaEntry>;

interface ContentSchemaEntry {
  type?: string;
  description?: string;
  properties?: Record<string, ContentSchemaEntry>;
  [key: string]: unknown;
}

interface FieldDescriptor {
  path: string;
  label: string;
  description: string | undefined;
  fieldType: 'text' | 'textarea' | 'number';
}

const TEXTAREA_KEYWORDS: ReadonlySet<string> = new Set([
  'description',
  'summary',
  'details',
  'body',
  'content',
  'bio',
  'about',
  'overview',
  'notes',
]);

function humanizeKey(key: string): string {
  return key.replaceAll('_', ' ').replaceAll(/\b\w/gu, (l: string) => l.toUpperCase());
}

function inferFieldType(key: string, entry: ContentSchemaEntry): 'text' | 'textarea' | 'number' {
  const entryType = entry.type?.toLowerCase();
  if (entryType === 'number' || entryType === 'integer') {
    return 'number';
  }
  if (entryType === 'text') {
    return 'textarea';
  }
  const lowKey = key.toLowerCase();
  for (const keyword of TEXTAREA_KEYWORDS) {
    if (lowKey.includes(keyword)) {
      return 'textarea';
    }
  }
  return 'text';
}

function flattenSchema(schema: ContentSchema, prefix: string): FieldDescriptor[] {
  const fields: FieldDescriptor[] = [];
  for (const [key, entry] of Object.entries(schema)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (entry.type === 'object' && entry.properties) {
      fields.push(...flattenSchema(entry.properties, path));
    } else {
      fields.push({
        path,
        label: humanizeKey(key),
        description: entry.description,
        fieldType: inferFieldType(key, entry),
      });
    }
  }
  return fields;
}

export type { ContentSchema, FieldDescriptor };
export { flattenSchema };
