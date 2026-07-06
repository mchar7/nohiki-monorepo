import { Eye, FileText, Plus } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { EmptyState } from './empty-state.tsx';

interface PanelEmptyStateProps {
  readonly variant: 'document' | 'preview';
  readonly onAction: () => void;
  readonly hasDatasets?: boolean;
}

export function PanelEmptyState({
  variant,
  onAction,
  hasDatasets = false,
}: PanelEmptyStateProps): JSX.Element {
  const { t } = useTranslation('common');

  const config = {
    document: {
      icon: FileText,
      title: hasDatasets
        ? t('emptyStates.document.selectTitle')
        : t('emptyStates.document.createTitle'),
      description: hasDatasets
        ? t('emptyStates.document.selectDescription')
        : t('emptyStates.document.createDescription'),
      actionLabel: hasDatasets
        ? t('emptyStates.document.createNewAction')
        : t('emptyStates.document.createAction'),
      actionIcon: Plus,
    },
    preview: {
      icon: Eye,
      title: t('emptyStates.preview.title'),
      description: t('emptyStates.preview.description'),
      actionLabel: t('emptyStates.preview.action'),
      actionIcon: Eye,
    },
  };

  const { icon, title, description, actionLabel } = config[variant];

  return (
    <EmptyState
      icon={icon}
      title={title}
      description={description}
      action={{
        label: actionLabel,
        onClick: onAction,
        variant: 'default',
      }}
      size="md"
      variant="card"
    />
  );
}
