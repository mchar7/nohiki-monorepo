export { authApi } from './auth-client.ts';
export {
  useLogin,
  useLogout,
  useRegister,
  useSession,
} from './auth-hooks.ts';
export {
  AUTH_TRANSITION_STORAGE_KEY,
  publishAuthTransition,
  subscribeToAuthTransitions,
} from './auth-sync.ts';
export {
  $api,
  createDevClient,
  fetchClient,
} from './client.ts';
export { CACHE_CONFIG } from './config.ts';
export { invalidateByPath } from './invalidation.ts';
export { ApiError } from './middleware.ts';
export { oauthApi } from './oauth-client.ts';
export {
  queryClient,
  queryKeys,
} from './queryClient.ts';
export {
  hydrateSkillIds,
  useSkillBatch,
} from './skills.ts';

export { SseStreamManager } from './sse/index.ts';
export {
  cancelScheduledRefresh,
  refreshToken,
  scheduleTokenRefresh,
  setTokenRefreshQueryClient,
} from './tokenRefresh.ts';
// Re-export all domain types so callers import from '@/shared/api' not the internal types.ts
export type {
  AttachmentResponse,
  CommandAcceptedResponse,
  CorrelationStatus,
  CurrencyCode,
  DocumentStatusResponse,
  FeatureImportanceRequest,
  FeedbackType,
  FitFactorContributionResponse,
  FitFactorName,
  FitRankingBreakdownResponse,
  GenerateDocumentRequest,
  GenerateTailoredDocumentRequest,
  JobCorrelationResponse,
  JobListingResponse,
  OAuthProvider,
  PaginatedResponseAttachmentResponse,
  PaginatedResponseJobCorrelationResponse,
  PaginatedResponseProfileResponse,
  PaymentFrequency,
  ProfileCreate,
  ProfileResponse,
  ProfileUpdate,
  ResolvedFeatureImportanceResponse,
  ScoreFeedbackType,
  SessionResponse,
  SkillSearchResponse,
  SkillSearchResult,
  TemplateFamilyResponse,
  TemplateResponse,
  UserResponse,
} from './types.ts';
