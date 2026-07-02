import type { JSX } from 'react';
import { useEffect, useRef, useState } from 'react';
import { useFormAutoSave } from '@/shared/lib/index.ts';
import { FEATURE_IMPORTANCE_DEFAULTS, FeatureImportanceSettings } from '@/shared/ui/index.ts';
import type { FeatureImportanceRequest, ResolvedFeatureImportanceResponse } from '../api/index.ts';
import { useResolvedFeatureImportance, useSetFeatureImportance } from '../api/index.ts';

/** Debounce delay for auto-saving feature importance slider changes. */
const IMPORTANCE_SAVE_DEBOUNCE_MS: number = 500;

/** Extract the 6 importance fields from the resolved response, stripping `source`. */
function extractImportanceValues(
  resolved: ResolvedFeatureImportanceResponse,
): FeatureImportanceRequest {
  const { source: _, ...values } = resolved;
  return values;
}

interface FeatureImportanceSectionProps {
  readonly profileId: string;
}

/** Renders feature importance sliders with debounced auto-save.
 *  Displayed independently of the profile edit form. Saves via its own mutation. */
export function FeatureImportanceSection({
  profileId,
}: FeatureImportanceSectionProps): JSX.Element | null {
  const { data: resolved, isLoading } = useResolvedFeatureImportance(profileId);
  const setImportance = useSetFeatureImportance();
  const userHasEdited = useRef(false);

  const [localValues, setLocalValues] = useState<FeatureImportanceRequest>(
    FEATURE_IMPORTANCE_DEFAULTS,
  );

  // Sync from server on initial load (skip once user has started editing)
  useEffect(() => {
    if (resolved && !userHasEdited.current) {
      setLocalValues(extractImportanceValues(resolved));
    }
  }, [resolved]);

  const handleChange = (values: FeatureImportanceRequest): void => {
    userHasEdited.current = true;
    setLocalValues(values);
  };

  useFormAutoSave({
    data: localValues,
    isDirty: userHasEdited.current,
    onSave: (values: FeatureImportanceRequest) =>
      setImportance.mutate({ params: { path: { pref_id: profileId } }, body: values }),
    debounceMs: IMPORTANCE_SAVE_DEBOUNCE_MS,
    enabled: userHasEdited.current,
  });

  if (isLoading) {
    return null;
  }

  return (
    <FeatureImportanceSettings
      values={localValues}
      onChange={handleChange}
      variant="card"
      showResetButton={true}
    />
  );
}
