/**
 * Re-exported schema types for clean imports across the application.
 *
 * This file is the internal source of domain types. Import through the public API:
 *   import type { ProfileResponse } from '@/shared/api';
 *
 * All types are derived from the OpenAPI schema via openapi-typescript.
 */
import type { components } from '@/api/schema.d.ts';

// Auth
export type CreateUserRequest = components['schemas']['CreateUserRequest'];
export type LoginRequest = components['schemas']['LoginRequest'];
export type LoginResponse = components['schemas']['LoginResponse'];
export type SessionResponse = components['schemas']['SessionResponse'];
export type UserCreateResponse = components['schemas']['UserCreateResponse'];
export type UserResponse = components['schemas']['UserResponse'];
export type UpdateUserRequest = components['schemas']['UpdateUserRequest'];

// OAuth
export type OAuthProvider = components['schemas']['OAuthProvider'];
export type OAuthProviderInfo = components['schemas']['OAuthProviderInfo'];
export type OAuthProvidersResponse = components['schemas']['OAuthProvidersResponse'];
export type OAuthIdentityResponse = components['schemas']['OAuthIdentityResponse'];
export type OAuthIdentitiesResponse = components['schemas']['OAuthIdentitiesResponse'];

// Profiles
export type ProfileCreate = components['schemas']['ProfileCreate'];
export type ProfileUpdate = components['schemas']['ProfileUpdate'];
export type ProfileResponse = components['schemas']['ProfileResponse'];
export type FeatureImportanceRequest = components['schemas']['FeatureImportanceRequest'];
export type ResolvedFeatureImportanceResponse =
  components['schemas']['ResolvedFeatureImportanceResponse'];
export type ExperiencePreferenceRequest = components['schemas']['ExperiencePreferenceRequest'];
export type ExperiencePreferenceResponse = components['schemas']['ExperiencePreferenceResponse'];
export type SalaryPreferenceRequest = components['schemas']['SalaryPreferenceRequest'];
export type SalaryPreferenceResponse = components['schemas']['SalaryPreferenceResponse'];

// Attachments
export type AttachmentResponse = components['schemas']['AttachmentResponse'];
export type InitiateUploadRequest = components['schemas']['InitiateUploadRequest'];
export type InitiateUploadResponse = components['schemas']['InitiateUploadResponse'];
export type CompleteUploadRequest = components['schemas']['CompleteUploadRequest'];

// Job Listings
export type JobListingResponse = components['schemas']['JobListingResponse'];

// Correlations
export type JobCorrelationResponse = components['schemas']['JobCorrelationResponse'];
export type FitFactorContributionResponse = components['schemas']['FitFactorContributionResponse'];
export type FitFactorName = components['schemas']['FitFactorName'];
export type FitRankingBreakdownResponse = components['schemas']['FitRankingBreakdownResponse'];
export type RecordFeedbackRequest = components['schemas']['RecordFeedbackRequest'];
export type ScoreFeedbackRequest = components['schemas']['ScoreFeedbackRequest'];
export type ScoreAdjustmentRequest = components['schemas']['ScoreAdjustmentRequest'];

// Documents
export type DocumentStatusResponse = components['schemas']['DocumentStatusResponse'];
export type GenerateDocumentRequest = components['schemas']['GenerateDocumentRequest'];
export type GenerateTailoredDocumentRequest =
  components['schemas']['GenerateTailoredDocumentRequest'];
export type GenerateDocumentResponse = components['schemas']['GenerateDocumentResponse'];

// Templates
export type TemplateFamilyResponse = components['schemas']['TemplateFamilyResponse'];
export type TemplateResponse = components['schemas']['TemplateResponse'];
export type TemplateCreateRequest = components['schemas']['TemplateCreateRequest'];
export type TemplateVersionAddRequest = components['schemas']['TemplateVersionAddRequest'];
export type TemplateValidationRequest = components['schemas']['TemplateValidationRequest'];
export type TemplateValidationResponse = components['schemas']['TemplateValidationResponse'];

// Schema families
export type SchemaFamilyResponse = components['schemas']['SchemaFamilyResponse'];
export type SchemaVersionResponse = components['schemas']['SchemaVersionResponse'];

// Shared
export type CommandAcceptedResponse = components['schemas']['CommandAcceptedResponse'];

// Pagination wrappers
export type PaginatedResponseAttachmentResponse =
  components['schemas']['PaginatedResponse_AttachmentResponse_'];
export type PaginatedResponseDocumentStatusResponse =
  components['schemas']['PaginatedResponse_DocumentStatusResponse_'];
export type PaginatedResponseJobCorrelationResponse =
  components['schemas']['PaginatedResponse_JobCorrelationResponse_'];
export type PaginatedResponseJobListingResponse =
  components['schemas']['PaginatedResponse_JobListingResponse_'];
export type PaginatedResponseProfileResponse =
  components['schemas']['PaginatedResponse_ProfileResponse_'];
export type PaginatedResponseSchemaFamilyResponse =
  components['schemas']['PaginatedResponse_SchemaFamilyResponse_'];
export type PaginatedResponseTemplateFamilyResponse =
  components['schemas']['PaginatedResponse_TemplateFamilyResponse_'];

// Skills
export type SkillBatchRequest = components['schemas']['SkillBatchRequest'];
export type SkillBatchResponse = components['schemas']['SkillBatchResponse'];
export type SkillSearchResponse = components['schemas']['SkillSearchResponse'];
export type SkillSearchResult = components['schemas']['SkillSearchResult'];

// Enum string literal types
export type CorrelationStatus = components['schemas']['CorrelationStatus'];
export type FeedbackType = components['schemas']['FeedbackType'];
export type ScoreFeedbackType = components['schemas']['ScoreFeedbackType'];
export type AccessScope = components['schemas']['AccessScope'];
export type WorkArrangement = components['schemas']['WorkArrangement'];
export type SeniorityLevel = components['schemas']['SeniorityLevel'];
export type PaymentFrequency = components['schemas']['PaymentFrequency'];
export type CurrencyCode = components['schemas']['CurrencyCode'];
