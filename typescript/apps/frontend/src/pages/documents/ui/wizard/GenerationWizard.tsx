import { GenerationProgress, useGenerateDocument } from '@features/document-generation';
import { Check } from 'lucide-react';
import { type JSX, useReducer, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { cn } from '@/shared/lib/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import type { DocType, WizardAction, WizardState } from '../../lib/wizardReducer.ts';
import {
  INITIAL_STATE,
  isStepValid,
  LAST_STEP,
  STEP_MATCH,
  STEP_PROFILE,
  STEP_REVIEW,
  STEP_TEMPLATE,
  STEP_TYPE,
  wizardReducer,
} from '../../lib/wizardReducer.ts';
import { MatchStep } from './MatchStep.tsx';
import { ProfileStep } from './ProfileStep.tsx';
import { ReviewStep } from './ReviewStep.tsx';
import { TemplateStep } from './TemplateStep.tsx';
import { TypeStep } from './TypeStep.tsx';

interface GenerationWizardProps {
  readonly preselectedTemplateId?: string | undefined;
}

const STEP_KEYS: readonly string[] = ['type', 'profile', 'match', 'template', 'review'] as const;

function GenerationWizard({ preselectedTemplateId }: GenerationWizardProps): JSX.Element {
  const { t } = useTranslation('documents');
  const [state, dispatch] = useReducer(wizardReducer, INITIAL_STATE);
  const [activeRequestId, setActiveRequestId] = useState<string | null>(null);
  const generateMutation = useGenerateDocument();

  const canAdvance = isStepValid(state, state.step);
  const isOnReviewStep = state.step === LAST_STEP;

  function handleGenerate(): void {
    if (!state.templateId) {
      return;
    }
    generateMutation.mutate(
      {
        body: { template_version_id: state.templateId, data: state.formData, output_format: 'pdf' },
      },
      {
        onSuccess: (data: { request_id: string }) => {
          toast.success(t('wizard.review.generationStarted'));
          setActiveRequestId(data.request_id);
        },
        onError: () => {
          toast.error(t('wizard.review.generationFailed'));
        },
      },
    );
  }

  function handleRetry(): void {
    setActiveRequestId(null);
    generateMutation.reset();
  }

  if (activeRequestId) {
    return (
      <div className="mx-auto max-w-3xl space-y-8">
        <GenerationProgress requestId={activeRequestId} onRetry={handleRetry} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <StepIndicator currentStep={state.step} />
      <section aria-label={t(`wizard.steps.${STEP_KEYS[state.step]}`)}>
        <WizardStepContent
          state={state}
          dispatch={dispatch}
          preselectedTemplateId={preselectedTemplateId}
          onGenerate={handleGenerate}
          isGenerating={generateMutation.isPending}
        />
      </section>
      <WizardNavigation
        step={state.step}
        canAdvance={canAdvance}
        isOnReviewStep={isOnReviewStep}
        onNext={() => dispatch({ type: 'NEXT_STEP' })}
        onPrev={() => dispatch({ type: 'PREV_STEP' })}
      />
    </div>
  );
}

interface WizardStepContentProps {
  readonly state: WizardState;
  readonly dispatch: React.Dispatch<WizardAction>;
  readonly preselectedTemplateId: string | undefined;
  readonly onGenerate: () => void;
  readonly isGenerating: boolean;
}

function WizardStepContent({
  state,
  dispatch,
  preselectedTemplateId,
  onGenerate,
  isGenerating,
}: WizardStepContentProps): JSX.Element | null {
  switch (state.step) {
    case STEP_TYPE:
      return (
        <TypeStep
          selected={state.docType}
          onSelect={(docType: DocType) => dispatch({ type: 'SET_DOC_TYPE', payload: docType })}
        />
      );
    case STEP_PROFILE:
      return (
        <ProfileStep
          selectedId={state.profileId}
          onSelect={(id: string) => dispatch({ type: 'SET_PROFILE', payload: id })}
        />
      );
    case STEP_MATCH:
      return (
        <MatchStep
          selectedId={state.matchId}
          profileId={state.profileId}
          onSelect={(id: string | null) => dispatch({ type: 'SET_MATCH', payload: id })}
        />
      );
    case STEP_TEMPLATE:
      return (
        <TemplateStep
          selectedId={state.templateId}
          docType={state.docType}
          preselectedTemplateId={preselectedTemplateId}
          onSelect={(id: string) => dispatch({ type: 'SET_TEMPLATE', payload: id })}
        />
      );
    case STEP_REVIEW:
      return (
        <ReviewStep
          state={state}
          onFormDataChange={(data: Record<string, unknown>) =>
            dispatch({ type: 'SET_FORM_DATA', payload: data })
          }
          onGenerate={onGenerate}
          isGenerating={isGenerating}
        />
      );
    default:
      return null;
  }
}

interface WizardNavigationProps {
  readonly step: number;
  readonly canAdvance: boolean;
  readonly isOnReviewStep: boolean;
  readonly onNext: () => void;
  readonly onPrev: () => void;
}

function WizardNavigation({
  step,
  canAdvance,
  isOnReviewStep,
  onNext,
  onPrev,
}: WizardNavigationProps): JSX.Element {
  const { t } = useTranslation('documents');

  return (
    <div className="flex justify-between border-t pt-6">
      <Button variant="outline" onClick={onPrev} disabled={step === 0}>
        {t('wizard.navigation.back')}
      </Button>
      {!isOnReviewStep && (
        <Button onClick={onNext} disabled={!canAdvance}>
          {t('wizard.navigation.next')}
        </Button>
      )}
    </div>
  );
}

function StepIndicator({ currentStep }: { readonly currentStep: number }): JSX.Element {
  const { t } = useTranslation('documents');

  return (
    <nav aria-label={t('wizard.a11y.progress')}>
      <ol className="flex items-center gap-2">
        {STEP_KEYS.map((key, index) => {
          const isActive = index === currentStep;
          const isCompleted = index < currentStep;
          const stepNumber = index + 1;
          return (
            <li key={key} className="flex items-center gap-2">
              {index > 0 && (
                <div
                  className={cn(
                    'hidden h-px w-8 sm:block',
                    isCompleted ? 'bg-primary' : 'bg-border',
                  )}
                />
              )}
              <div
                className={cn(
                  'flex items-center gap-2 rounded-full px-3 py-1.5 font-medium text-xs transition-colors',
                  isActive && 'bg-primary text-primary-foreground',
                  isCompleted && 'bg-primary/10 text-primary',
                  !(isActive || isCompleted) && 'bg-muted text-muted-foreground',
                )}
                aria-current={isActive ? 'step' : undefined}
              >
                {isCompleted ? (
                  <Check className="size-3.5" aria-hidden="true" />
                ) : (
                  <span>{stepNumber}</span>
                )}
                <span className="hidden sm:inline">{t(`wizard.steps.${key}`)}</span>
              </div>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export { GenerationWizard };
