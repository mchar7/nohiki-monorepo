import { AlertTriangle } from 'lucide-react';
import { type JSX, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from './button.tsx';
import { Checkbox } from './checkbox.tsx';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './dialog.tsx';

type RenderMethod = 'html' | 'image';

interface TemplateJsWarningProps {
  open: boolean;
  templateName: string;
  templateVersion: string;
  reason?: string | undefined;
  onChoice: (method: RenderMethod, remember: boolean) => void;
}

export function TemplateJsWarning({
  open,
  templateName,
  templateVersion,
  reason,
  onChoice,
}: Readonly<TemplateJsWarningProps>): JSX.Element {
  const { t } = useTranslation('omakase.templateStudio');
  const rememberId = useId();
  const [remember, setRemember] = useState(false);

  const handleChoice = (method: RenderMethod): void => {
    onChoice(method, remember);
    setRemember(false);
  };

  const handleRememberChange = (checked: boolean): void => {
    setRemember(checked);
  };

  const handleNoOpOpenChange = (): void => {
    /* controlled externally via onChoice */
  };

  const handleRenderImage = (): void => {
    handleChoice('image');
  };

  const handleRenderHtml = (): void => {
    handleChoice('html');
  };

  return (
    <Dialog open={open} onOpenChange={handleNoOpOpenChange}>
      {/* a11y fix: hide close button since onOpenChange is a no-op; this is a
         forced-choice dialog where users must pick a render method */}
      <DialogContent className="sm:max-w-md" showCloseButton={false}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="size-5 text-amber-500" aria-hidden="true" />
            {t('jsWarning.title')}
          </DialogTitle>
          <DialogDescription className="text-left">
            {t('jsWarning.description')}
            {reason ? (
              <span className="mt-2 block font-medium text-foreground">
                {`${t('jsWarning.reason')}: ${reason}`}
              </span>
            ) : null}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/20">
            <p className="text-amber-800 text-sm dark:text-amber-200">
              {t('jsWarning.choiceDescription')}
            </p>
          </div>

          <div className="flex items-center space-x-2">
            <Checkbox id={rememberId} checked={remember} onCheckedChange={handleRememberChange} />
            <label
              htmlFor={rememberId}
              className="font-medium text-sm leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
            >
              {t('jsWarning.dontAskAgain', { template: `${templateName}@${templateVersion}` })}
            </label>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={handleRenderImage} className="sm:mr-2">
            {t('jsWarning.renderImage')}
          </Button>
          <Button onClick={handleRenderHtml}>{t('jsWarning.renderHtml')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
