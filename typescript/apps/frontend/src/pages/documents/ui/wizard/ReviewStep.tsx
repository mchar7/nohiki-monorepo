import { useAccount } from '@features/account/index.ts';
import type { ContentSchema } from '@features/document-generation';
import { mapDataToTemplateVariables } from '@features/document-generation';
import { useMyCorrelations } from '@features/job-matching/index.ts';
import { useTemplateFamilies } from '@features/omakase/document-builder';
import { useProfiles } from '@features/profile-management/index.ts';
import { Loader2 } from 'lucide-react';
import type { JSX } from 'react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { Input } from '@/shared/ui/input.tsx';
import { Label } from '@/shared/ui/label.tsx';
import type { WizardState } from '../../lib/wizardReducer.ts';

interface ReviewStepProps {
  readonly state: WizardState;
  readonly onFormDataChange: (data: Record<string, unknown>) => void;
  readonly onGenerate: () => void;
  readonly isGenerating: boolean;
}

interface SchemaFieldDefinition {
  title?: string;
  description?: string;
  type?: string;
}

interface SchemaWithProperties {
  properties?: Record<string, unknown>;
  required?: readonly string[];
}

function buildLookupMap<T>(
  items: readonly T[] | undefined,
  getKey: (item: T) => string | null | undefined,
): Map<string, T> {
  const map = new Map<string, T>();

  for (const item of items ?? []) {
    const key = getKey(item);
    if (key) {
      map.set(key, item);
    }
  }

  return map;
}

interface ResolvedWizardData {
  profile: ReturnType<typeof useProfiles>['data'] extends { items: Array<infer T> } | undefined
    ? T | undefined
    : never;
  correlation: ReturnType<typeof useMyCorrelations>['data'] extends
    | { items: Array<infer T> }
    | undefined
    ? T | undefined
    : never;
  templateFamily: ReturnType<typeof useTemplateFamilies>['data'] extends
    | { items: Array<infer T> }
    | undefined
    ? T | undefined
    : never;
}

function useResolvedWizardData(state: WizardState): ResolvedWizardData {
  const { data: profilesData } = useProfiles();
  const { data: correlationsData } = useMyCorrelations();
  const { data: templatesData } = useTemplateFamilies();

  const profilesById = buildLookupMap(profilesData?.items, (profile) => profile.id);
  const correlationsById = buildLookupMap(correlationsData?.items, (correlation) => correlation.id);
  const templateFamiliesByVersionId = buildLookupMap(
    templatesData?.items,
    (family) => family.latest_version?.id,
  );

  return {
    profile: state.profileId ? profilesById.get(state.profileId) : undefined,
    correlation: state.matchId ? correlationsById.get(state.matchId) : undefined,
    templateFamily: state.templateId
      ? templateFamiliesByVersionId.get(state.templateId)
      : undefined,
  };
}

/**
 * Runs once to pre-fill form fields from profile/account/match data.
 * Skips subsequent runs so user edits are preserved.
 */
function usePreFillFormData(
  contentSchema: ContentSchema | null | undefined,
  data: ResolvedWizardData,
  state: WizardState,
  onFormDataChange: (formData: Record<string, unknown>) => void,
): void {
  const { data: accountData } = useAccount();
  const hasPreFilled = useRef(false);

  useEffect(() => {
    if (hasPreFilled.current || !contentSchema) {
      return;
    }

    const mapped = mapDataToTemplateVariables(
      contentSchema as ContentSchema,
      data.profile,
      data.correlation,
      accountData,
    );

    if (Object.keys(mapped).length === 0) {
      return;
    }

    hasPreFilled.current = true;
    onFormDataChange({ ...mapped, ...state.formData });
  }, [
    contentSchema,
    data.profile,
    data.correlation,
    accountData,
    state.formData,
    onFormDataChange,
  ]);
}

function SummaryCard({
  state,
  profile,
  correlation,
  templateFamily,
}: {
  readonly state: WizardState;
  readonly profile: ResolvedWizardData['profile'];
  readonly correlation: ResolvedWizardData['correlation'];
  readonly templateFamily: ResolvedWizardData['templateFamily'];
}): JSX.Element {
  const { t } = useTranslation('documents');
  const docTypeLabel =
    state.docType === 'resume' ? t('wizard.type.resume') : t('wizard.type.coverLetter');

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t('wizard.review.summary')}</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="space-y-3 text-sm">
          <div className="flex justify-between">
            <dt className="text-muted-foreground">{t('wizard.review.selectedType')}</dt>
            <dd className="font-medium">{docTypeLabel}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">{t('wizard.review.selectedProfile')}</dt>
            <dd className="font-medium">{profile?.pref_name ?? '-'}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">{t('wizard.review.selectedMatch')}</dt>
            <dd className="font-medium">
              {correlation ? correlation.listing_title : t('wizard.review.noMatch')}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">{t('wizard.review.selectedTemplate')}</dt>
            <dd className="font-medium">{templateFamily?.name ?? '-'}</dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

function SchemaFieldsCard({
  schemaProperties,
  state,
  onFormDataChange,
}: {
  readonly schemaProperties: Record<string, unknown>;
  readonly state: WizardState;
  readonly onFormDataChange: (data: Record<string, unknown>) => void;
}): JSX.Element {
  const { t } = useTranslation('documents');

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t('wizard.review.additionalData')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {Object.entries(schemaProperties).map(([key, schemaDef]) => {
          const fieldSchema = schemaDef as SchemaFieldDefinition;
          const fieldLabel = fieldSchema.title ?? key;
          const fieldId = `wizard-field-${key}`;
          return (
            <div key={key} className="space-y-2">
              <Label htmlFor={fieldId}>{fieldLabel}</Label>
              <Input
                id={fieldId}
                value={String(state.formData[key] ?? '')}
                placeholder={fieldSchema.description ?? ''}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                  onFormDataChange({ ...state.formData, [key]: e.target.value });
                }}
              />
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function ReviewStep({
  state,
  onFormDataChange,
  onGenerate,
  isGenerating,
}: ReviewStepProps): JSX.Element {
  const { t } = useTranslation('documents');
  const resolved = useResolvedWizardData(state);
  const [nameError, setNameError] = useState<string | null>(null);

  const contentSchema = resolved.templateFamily?.latest_version?.content_schema;
  const schemaProperties = (contentSchema as SchemaWithProperties | undefined)?.properties;

  usePreFillFormData(contentSchema as ContentSchema | undefined, resolved, state, onFormDataChange);
  function handleGenerate(): void {
    const requiresFullName = (
      contentSchema as SchemaWithProperties | undefined
    )?.required?.includes('full_name');
    const fullName = state.formData.full_name;
    if (requiresFullName && (typeof fullName !== 'string' || fullName.trim() === '')) {
      const message = t('wizard.review.nameRequired');
      setNameError(message);
      toast.error(message);
      return;
    }
    setNameError(null);
    onGenerate();
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-semibold text-lg">{t('wizard.review.heading')}</h2>
        <p className="text-muted-foreground text-sm">{t('wizard.review.description')}</p>
      </div>

      <SummaryCard state={state} {...resolved} />

      {schemaProperties && Object.keys(schemaProperties).length > 0 && (
        <SchemaFieldsCard
          schemaProperties={schemaProperties}
          state={state}
          onFormDataChange={onFormDataChange}
        />
      )}

      {nameError ? (
        <p role="alert" className="text-destructive text-sm">
          {nameError}
        </p>
      ) : null}

      <div className="flex justify-end">
        <Button onClick={handleGenerate} disabled={isGenerating} size="lg">
          {isGenerating ? (
            <>
              <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />
              {t('wizard.review.generating')}
            </>
          ) : (
            t('wizard.navigation.generate')
          )}
        </Button>
      </div>
    </div>
  );
}

export { ReviewStep };
