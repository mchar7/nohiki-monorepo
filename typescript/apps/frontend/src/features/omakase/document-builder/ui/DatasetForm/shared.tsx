import { Label } from '@shared/ui/label.tsx';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@shared/ui/tooltip.tsx';
import { HelpCircle } from 'lucide-react';
import type { JSONSchemaProperty } from '@/shared/model/index.ts';
import { getUIHints } from '../../lib/template.ts';

/** Threshold for maxLength above which a string field auto-renders as a textarea */
const TEXTAREA_AUTO_THRESHOLD_LENGTH: number = 100;

// Helper functions for field rendering
export function getFieldTitle(fieldSchema: JSONSchemaProperty, key: string): string {
  return (
    fieldSchema.title ||
    key.replaceAll('_', ' ').replaceAll(/\b\w/gu, (l: string) => l.toUpperCase())
  );
}

export function getInputType(fieldSchema: JSONSchemaProperty): string {
  if (fieldSchema.format === 'email') {
    return 'email';
  }
  if (fieldSchema.format === 'uri') {
    return 'url';
  }
  if (fieldSchema.format === 'date') {
    return 'date';
  }
  if (fieldSchema.type === 'number' || fieldSchema.type === 'integer') {
    return 'number';
  }
  return 'text';
}

export function getFieldWidget(fieldSchema: JSONSchemaProperty, key: string): string | undefined {
  const fieldUIHints = getUIHints(fieldSchema);

  return (
    fieldUIHints.widget ||
    (fieldSchema.type === 'string' &&
    ((fieldSchema.maxLength && fieldSchema.maxLength > TEXTAREA_AUTO_THRESHOLD_LENGTH) ||
      key.includes('description') ||
      key.includes('summary') ||
      key.includes('details'))
      ? 'textarea'
      : undefined)
  );
}

export function renderFieldLabel(
  fieldTitle: string,
  fieldDescription: string | undefined,
): React.ReactNode {
  return (
    <div className="flex items-center gap-2">
      <Label className="font-medium text-sm">{fieldTitle}</Label>
      {fieldDescription ? (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild={true}>
              <HelpCircle className="size-4 cursor-help text-muted-foreground" />
            </TooltipTrigger>
            <TooltipContent side="right" className="max-w-xs">
              <p className="text-sm">{fieldDescription}</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : null}
    </div>
  );
}
