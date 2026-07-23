import { Label } from '@shared/ui/label.tsx';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@shared/ui/tooltip.tsx';
import { HelpCircle } from 'lucide-react';

function FieldLabelWithTooltip({
  label,
  description,
}: {
  readonly label: string;
  readonly description: string | undefined;
}): React.ReactElement {
  return (
    <div className="flex items-center gap-2">
      <Label className="font-medium text-sm">{label}</Label>
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

export { FieldLabelWithTooltip };
