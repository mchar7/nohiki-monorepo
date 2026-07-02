import {
  Label,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@shared/ui/index.ts';
import { HelpCircle } from 'lucide-react';
import type { JSX } from 'react';

const REQUIRED_INDICATOR = '*';

function FieldLabel({
  fieldId,
  label,
  required,
  requiredTitle,
  description,
}: {
  readonly fieldId: string;
  readonly label: string;
  readonly required: boolean;
  readonly requiredTitle: string;
  readonly description: string | undefined;
}): JSX.Element {
  return (
    <div className="flex items-center gap-2">
      <Label htmlFor={fieldId} className="font-medium text-sm">
        {label}
        {required ? (
          <span className="ml-1 text-destructive" title={requiredTitle}>
            {REQUIRED_INDICATOR}
          </span>
        ) : null}
      </Label>
      {description ? (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild={true}>
              <HelpCircle className="size-4 cursor-help text-muted-foreground" />
            </TooltipTrigger>
            <TooltipContent side="right" className="max-w-xs">
              <p className="text-sm">{description}</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : null}
    </div>
  );
}

function CheckboxLayout({
  renderedField,
  description,
  errorMessage,
}: {
  readonly renderedField: JSX.Element;
  readonly description: string | undefined;
  readonly errorMessage: JSX.Element | null;
}): JSX.Element {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        {renderedField}
        {description ? (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild={true}>
                <HelpCircle className="size-4 cursor-help text-muted-foreground" />
              </TooltipTrigger>
              <TooltipContent side="right" className="max-w-xs">
                <p className="text-sm">{description}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : null}
      </div>
      {errorMessage}
    </div>
  );
}

function StandardFieldLayout({
  fieldId,
  label,
  required,
  requiredTitle,
  description,
  renderedField,
  errorMessage,
}: {
  readonly fieldId: string;
  readonly label: string;
  readonly required: boolean;
  readonly requiredTitle: string;
  readonly description: string | undefined;
  readonly renderedField: JSX.Element;
  readonly errorMessage: JSX.Element | null;
}): JSX.Element {
  return (
    <div className="space-y-2">
      <FieldLabel
        fieldId={fieldId}
        label={label}
        required={required}
        requiredTitle={requiredTitle}
        description={description}
      />
      <div id={fieldId}>{renderedField}</div>
      {errorMessage}
    </div>
  );
}

export { CheckboxLayout, StandardFieldLayout };
