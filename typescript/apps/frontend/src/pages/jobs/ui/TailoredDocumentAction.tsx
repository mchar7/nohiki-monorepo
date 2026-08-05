import { GenerationProgress, useGenerateTailoredDocument } from '@features/document-generation';
import { useTemplateFamilies } from '@features/omakase/document-builder';
import { AlertCircle, FileText, Loader2, RefreshCw, X } from 'lucide-react';
import { type FormEvent, type JSX, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, AlertDescription, AlertTitle } from '@/shared/ui/alert.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { Label } from '@/shared/ui/label.tsx';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/ui/select.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';

type OutputFormat = 'pdf' | 'html' | 'png';

const OUTPUT_FORMATS: readonly OutputFormat[] = ['pdf', 'html', 'png'];

interface TailoredDocumentActionProps {
  readonly correlationId: string;
  readonly jobTitle: string;
  readonly company?: string | null;
}

function TailoredDocumentAction({
  correlationId,
  jobTitle,
  company,
}: TailoredDocumentActionProps): JSX.Element {
  const { t } = useTranslation('jobs');
  const [isOpen, setIsOpen] = useState(false);
  const [templateId, setTemplateId] = useState('');
  const [outputFormat, setOutputFormat] = useState<OutputFormat>('pdf');
  const [requestId, setRequestId] = useState<string | null>(null);
  const templateLabelId = useId();
  const formatLabelId = useId();
  const templates = useTemplateFamilies({ page: 1, page_size: 100 });
  const generation = useGenerateTailoredDocument();
  const availableTemplates = templates.data?.items.filter((family) => family.latest_version) ?? [];

  const generate = (): void => {
    if (!templateId || generation.isPending) {
      return;
    }

    generation.mutate(
      {
        body: {
          job_correlation_id: correlationId,
          template_id: templateId,
          output_format: outputFormat,
        },
      },
      {
        onSuccess: (response: { readonly request_id: string }) => setRequestId(response.request_id),
      },
    );
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    generate();
  };

  const handleRetry = (): void => {
    setRequestId(null);
    generation.reset();
  };

  if (!isOpen) {
    return (
      <Button type="button" variant="outline" size="sm" onClick={() => setIsOpen(true)}>
        <FileText aria-hidden="true" />
        {t('tailoredDocument.open')}
      </Button>
    );
  }

  return (
    <section
      className="rounded-lg border border-border/70 bg-muted/20 p-4"
      aria-labelledby="tailored-document-title"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h3 id="tailored-document-title" className="font-semibold text-sm">
            {t('tailoredDocument.title')}
          </h3>
          <p className="text-muted-foreground text-sm">
            {t('tailoredDocument.context', {
              title: jobTitle,
              company: company ?? t('tailoredDocument.unknownCompany'),
            })}
          </p>
        </div>
        {requestId === null ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="-mt-2 -mr-2"
            onClick={() => setIsOpen(false)}
            aria-label={t('tailoredDocument.close')}
          >
            <X aria-hidden="true" />
          </Button>
        ) : null}
      </div>

      {requestId ? (
        <div className="mt-4">
          <GenerationProgress requestId={requestId} onRetry={handleRetry} />
        </div>
      ) : (
        <TailoredDocumentForm
          templateLabelId={templateLabelId}
          formatLabelId={formatLabelId}
          templateId={templateId}
          outputFormat={outputFormat}
          availableTemplates={availableTemplates}
          templates={templates}
          generation={generation}
          onTemplateChange={setTemplateId}
          onFormatChange={setOutputFormat}
          onSubmit={handleSubmit}
          onGenerate={generate}
        />
      )}
    </section>
  );
}

interface TailoredDocumentFormProps {
  readonly templateLabelId: string;
  readonly formatLabelId: string;
  readonly templateId: string;
  readonly outputFormat: OutputFormat;
  readonly availableTemplates: NonNullable<ReturnType<typeof useTemplateFamilies>['data']>['items'];
  readonly templates: ReturnType<typeof useTemplateFamilies>;
  readonly generation: ReturnType<typeof useGenerateTailoredDocument>;
  readonly onTemplateChange: (value: string) => void;
  readonly onFormatChange: (value: OutputFormat) => void;
  readonly onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  readonly onGenerate: () => void;
}

function TailoredDocumentForm({
  templateLabelId,
  formatLabelId,
  templateId,
  outputFormat,
  availableTemplates,
  templates,
  generation,
  onTemplateChange,
  onFormatChange,
  onSubmit,
  onGenerate,
}: TailoredDocumentFormProps): JSX.Element {
  const { t } = useTranslation('jobs');

  if (templates.isLoading) {
    return (
      <div className="mt-4 grid gap-3 sm:grid-cols-2" aria-busy="true" aria-live="polite">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
        <span className="sr-only">{t('tailoredDocument.loadingTemplates')}</span>
      </div>
    );
  }

  if (templates.error) {
    return (
      <Alert variant="destructive" className="mt-4" aria-live="assertive">
        <AlertCircle aria-hidden="true" />
        <AlertTitle>{t('tailoredDocument.templateErrorTitle')}</AlertTitle>
        <AlertDescription>
          <p>
            {templates.error instanceof Error
              ? templates.error.message
              : t('tailoredDocument.templateErrorDescription')}
          </p>
          <Button type="button" variant="outline" size="sm" onClick={() => templates.refetch()}>
            <RefreshCw aria-hidden="true" />
            {t('tailoredDocument.retry')}
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  if (availableTemplates.length === 0) {
    return (
      <Alert className="mt-4" aria-live="polite">
        <FileText aria-hidden="true" />
        <AlertTitle>{t('tailoredDocument.emptyTitle')}</AlertTitle>
        <AlertDescription>{t('tailoredDocument.emptyDescription')}</AlertDescription>
      </Alert>
    );
  }

  return (
    <form className="mt-4 space-y-3" onSubmit={onSubmit} aria-busy={generation.isPending}>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_8rem_auto] sm:items-end">
        <div className="space-y-1.5">
          <Label id={templateLabelId}>{t('tailoredDocument.templateLabel')}</Label>
          <Select
            value={templateId}
            onValueChange={onTemplateChange}
            disabled={generation.isPending}
          >
            <SelectTrigger className="w-full" aria-labelledby={templateLabelId}>
              <SelectValue placeholder={t('tailoredDocument.templatePlaceholder')} />
            </SelectTrigger>
            <SelectContent>
              {availableTemplates.map((family) => (
                <SelectItem key={family.id} value={family.id}>
                  {family.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label id={formatLabelId}>{t('tailoredDocument.formatLabel')}</Label>
          <Select
            value={outputFormat}
            onValueChange={(value: string) => onFormatChange(value as OutputFormat)}
            disabled={generation.isPending}
          >
            <SelectTrigger className="w-full" aria-labelledby={formatLabelId}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {OUTPUT_FORMATS.map((format) => (
                <SelectItem key={format} value={format}>
                  {format.toUpperCase()}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Button type="submit" disabled={!templateId || generation.isPending}>
          {generation.isPending ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
          {generation.isPending ? t('tailoredDocument.generating') : t('tailoredDocument.generate')}
        </Button>
      </div>

      <div aria-live="polite" className="min-h-5 text-muted-foreground text-xs">
        {generation.isPending ? t('tailoredDocument.pending') : null}
      </div>

      {generation.error ? (
        <Alert variant="destructive" aria-live="assertive">
          <AlertCircle aria-hidden="true" />
          <AlertTitle>{t('tailoredDocument.generationErrorTitle')}</AlertTitle>
          <AlertDescription>
            <p>
              {generation.error instanceof Error
                ? generation.error.message
                : t('tailoredDocument.generationErrorDescription')}
            </p>
            <Button type="button" variant="outline" size="sm" onClick={onGenerate}>
              <RefreshCw aria-hidden="true" />
              {t('tailoredDocument.retry')}
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}
    </form>
  );
}

export type { TailoredDocumentActionProps };
export { TailoredDocumentAction };
