import {
  Briefcase,
  Clock,
  DollarSign,
  Laptop,
  type LucideIcon,
  MapPin,
  Sparkles,
} from 'lucide-react';
import type { FeatureImportanceRequest } from '@/shared/api/index.ts';

interface FeatureConfig {
  readonly key: keyof FeatureImportanceRequest;
  readonly icon: LucideIcon;
  readonly labelKey: string;
  readonly descriptionKey: string;
}

const FEATURE_CONFIGS: readonly FeatureConfig[] = [
  {
    key: 'skill_match_importance',
    icon: Sparkles,
    labelKey: 'profiles:featureImportance.skillMatch',
    descriptionKey: 'profiles:featureImportance.skillMatchDescription',
  },
  {
    key: 'location_importance',
    icon: MapPin,
    labelKey: 'profiles:featureImportance.location',
    descriptionKey: 'profiles:featureImportance.locationDescription',
  },
  {
    key: 'work_arrangement_importance',
    icon: Laptop,
    labelKey: 'profiles:featureImportance.workArrangement',
    descriptionKey: 'profiles:featureImportance.workArrangementDescription',
  },
  {
    key: 'experience_importance',
    icon: Briefcase,
    labelKey: 'profiles:featureImportance.experience',
    descriptionKey: 'profiles:featureImportance.experienceDescription',
  },
  {
    key: 'salary_importance',
    icon: DollarSign,
    labelKey: 'profiles:featureImportance.salary',
    descriptionKey: 'profiles:featureImportance.salaryDescription',
  },
  {
    key: 'recency_importance',
    icon: Clock,
    labelKey: 'profiles:featureImportance.recency',
    descriptionKey: 'profiles:featureImportance.recencyDescription',
  },
] as const satisfies readonly FeatureConfig[];

type FeatureLabelKey = (typeof FEATURE_CONFIGS)[number]['labelKey'];
type FeatureDescKey = (typeof FEATURE_CONFIGS)[number]['descriptionKey'];

/** Default importance value for all features (neutral weight, 50%). */
const DEFAULT_IMPORTANCE_VALUE: number = 50;

const FEATURE_IMPORTANCE_DEFAULTS: FeatureImportanceRequest = {
  skill_match_importance: DEFAULT_IMPORTANCE_VALUE,
  location_importance: DEFAULT_IMPORTANCE_VALUE,
  work_arrangement_importance: DEFAULT_IMPORTANCE_VALUE,
  experience_importance: DEFAULT_IMPORTANCE_VALUE,
  salary_importance: DEFAULT_IMPORTANCE_VALUE,
  recency_importance: DEFAULT_IMPORTANCE_VALUE,
};

export type { FeatureDescKey, FeatureLabelKey };
export { DEFAULT_IMPORTANCE_VALUE, FEATURE_CONFIGS, FEATURE_IMPORTANCE_DEFAULTS };
