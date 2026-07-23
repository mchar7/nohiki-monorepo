import { logComponentError } from '@shared/lib/index.ts';
import { Button } from '@shared/ui/button.tsx';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@shared/ui/dialog.tsx';
import { Input } from '@shared/ui/input.tsx';
import { Label } from '@shared/ui/label.tsx';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@shared/ui/select.tsx';
import { Loader2 } from 'lucide-react';
import type { JSX } from 'react';
import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TemplateFamilyResponse } from '@/shared/api';
import { useDocumentBuilderStore } from '../../model/index.ts';

interface CreateDatasetModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: (datasetId: string) => void;
}

interface TemplateFamilyDetailsProps {
  readonly family: TemplateFamilyResponse;
  readonly detailsLabel: string;
  readonly engineLabel: string;
  readonly versionLabel: string;
}

function TemplateFamilyDetails({
  family,
  detailsLabel,
  engineLabel,
  versionLabel,
}: TemplateFamilyDetailsProps): JSX.Element {
  return (
    <div className="rounded-md bg-muted p-3">
      <h3 className="mb-1 font-medium text-foreground text-sm">{detailsLabel}</h3>
      <p className="text-muted-foreground text-xs">{engineLabel}</p>
      <p className="text-muted-foreground text-xs">
        {versionLabel} {family.latest_version?.version}
      </p>
    </div>
  );
}

function useCreateDatasetForm(
  isOpen: boolean,
  templateFamilies: TemplateFamilyResponse[],
): {
  name: string;
  setName: (name: string) => void;
  selectedFamilyId: string;
  setSelectedFamilyId: (id: string) => void;
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;
  currentTemplate: ReturnType<typeof useDocumentBuilderStore.getState>['currentTemplate'];
  createDataset: ReturnType<typeof useDocumentBuilderStore.getState>['createDataset'];
  selectedFamily: TemplateFamilyResponse | undefined;
  isFormValid: boolean;
} {
  const currentTemplate = useDocumentBuilderStore((state) => state.currentTemplate);
  const createDataset = useDocumentBuilderStore((state) => state.createDataset);
  const [name, setName] = useState('');
  const [selectedFamilyId, setSelectedFamilyId] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setName('');
      setSelectedFamilyId(templateFamilies[0]?.id || '');
    }
  }, [isOpen, templateFamilies]);

  const familyIndex = new Map(templateFamilies.map((f) => [f.id, f]));

  return {
    name,
    setName,
    selectedFamilyId,
    setSelectedFamilyId,
    isLoading,
    setIsLoading,
    currentTemplate,
    createDataset,
    selectedFamily: familyIndex.get(selectedFamilyId),
    isFormValid: name.trim().length > 0 && selectedFamilyId.length > 0,
  };
}

function handleFormSubmit(
  form: ReturnType<typeof useCreateDatasetForm>,
  onSuccess: ((datasetId: string) => void) | undefined,
  onClose: () => void,
): (e: React.FormEvent<HTMLFormElement>) => void {
  return (e: React.FormEvent<HTMLFormElement>): void => {
    e.preventDefault();
    if (!(form.name.trim() && form.selectedFamilyId && form.currentTemplate) || form.isLoading) {
      return;
    }
    form.setIsLoading(true);
    try {
      const newDatasetId = form.createDataset({
        name: form.name.trim(),
        templateVersionId: form.currentTemplate.id,
        data: {},
      });
      onSuccess?.(newDatasetId);
      onClose();
    } catch (error) {
      logComponentError('CreateDatasetModal', error, { context: 'Failed to create dataset' });
    } finally {
      form.setIsLoading(false);
    }
  };
}

interface FormActionsProps {
  readonly onClose: () => void;
  readonly isLoading: boolean;
  readonly isFormValid: boolean;
  readonly submitLabel: string;
  readonly cancelLabel: string;
}

function FormActions({
  onClose,
  isLoading,
  isFormValid,
  submitLabel,
  cancelLabel,
}: FormActionsProps): JSX.Element {
  return (
    <div className="flex gap-3 pt-4">
      <Button
        type="button"
        onClick={onClose}
        variant="outline"
        className="flex-1"
        disabled={isLoading}
      >
        {cancelLabel}
      </Button>
      <Button type="submit" disabled={!isFormValid || isLoading} className="flex-1">
        {isLoading ? <Loader2 className="mr-2 size-4 animate-spin" /> : null}
        {submitLabel}
      </Button>
    </div>
  );
}

export function CreateDatasetModal({
  isOpen,
  onClose,
  onSuccess,
}: Readonly<CreateDatasetModalProps>): JSX.Element {
  const { t } = useTranslation(['omakase.editor', 'common']);
  const templateFamilies = useDocumentBuilderStore((state) => state.templateFamilies);
  const form = useCreateDatasetForm(isOpen, templateFamilies);
  const nameId = useId();
  const familySelectId = useId();
  const submitLabel = form.isLoading ? t('datasets.create.creating') : t('datasets.create.create');

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('datasets.create.title')}</DialogTitle>
          <DialogDescription>{t('datasets.create.description')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleFormSubmit(form, onSuccess, onClose)} className="space-y-4">
          <div>
            <Label htmlFor={nameId}>{t('datasets.create.nameLabel')}</Label>
            <Input
              id={nameId}
              type="text"
              value={form.name}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => form.setName(e.target.value)}
              placeholder={t('datasets.create.namePlaceholder')}
              disabled={form.isLoading}
              autoFocus={true}
            />
          </div>

          <div>
            <Label htmlFor={familySelectId}>{t('datasets.create.templateLabel')}</Label>
            <Select
              value={form.selectedFamilyId}
              onValueChange={form.setSelectedFamilyId}
              disabled={form.isLoading}
            >
              <SelectTrigger id={familySelectId}>
                <SelectValue placeholder={t('datasets.create.templatePlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                {templateFamilies.map((family) => (
                  <SelectItem key={family.id} value={family.id}>
                    {family.display_name || t('common:unavailable')}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {form.selectedFamily ? (
            <TemplateFamilyDetails
              family={form.selectedFamily}
              detailsLabel={t('datasets.create.templateDetails')}
              engineLabel={t('datasets.create.engine')}
              versionLabel={t('datasets.create.latestVersion')}
            />
          ) : null}

          <FormActions
            onClose={onClose}
            isLoading={form.isLoading}
            isFormValid={form.isFormValid}
            submitLabel={submitLabel}
            cancelLabel={t('datasets.create.cancel')}
          />
        </form>
      </DialogContent>
    </Dialog>
  );
}
