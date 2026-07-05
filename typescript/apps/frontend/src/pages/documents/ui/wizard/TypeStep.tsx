import { FileText, Mail } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib/index.ts';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import type { DocType } from '../../lib/wizardReducer.ts';

interface TypeStepProps {
  readonly selected: DocType | null;
  readonly onSelect: (docType: DocType) => void;
}

const DOC_TYPES: ReadonlyArray<{
  value: DocType;
  icon: typeof FileText;
  titleKey: string;
  descriptionKey: string;
}> = [
  {
    value: 'resume',
    icon: FileText,
    titleKey: 'wizard.type.resume',
    descriptionKey: 'wizard.type.resumeDescription',
  },
  {
    value: 'cover_letter',
    icon: Mail,
    titleKey: 'wizard.type.coverLetter',
    descriptionKey: 'wizard.type.coverLetterDescription',
  },
];

function TypeStep({ selected, onSelect }: TypeStepProps): JSX.Element {
  const { t } = useTranslation('documents');

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-semibold text-lg">{t('wizard.type.heading')}</h2>
      </div>
      <div
        className="grid gap-4 sm:grid-cols-2"
        role="radiogroup"
        aria-label={t('wizard.steps.type')}
      >
        {DOC_TYPES.map(({ value, icon: Icon, titleKey, descriptionKey }) => {
          const isSelected = selected === value;
          return (
            <Card
              key={value}
              role="radio"
              aria-checked={isSelected}
              tabIndex={0}
              className={cn(
                'cursor-pointer transition-colors hover:border-primary/50',
                isSelected && 'border-primary ring-2 ring-primary/20',
              )}
              onClick={() => onSelect(value)}
              onKeyDown={(e: React.KeyboardEvent) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelect(value);
                }
              }}
            >
              <CardHeader>
                <div className="mb-2 flex size-10 items-center justify-center rounded-lg bg-primary/10">
                  <Icon className="size-5 text-primary" aria-hidden="true" />
                </div>
                <CardTitle>{t(titleKey)}</CardTitle>
                <CardDescription>{t(descriptionKey)}</CardDescription>
              </CardHeader>
              <CardContent />
            </Card>
          );
        })}
      </div>
    </div>
  );
}

export { TypeStep };
