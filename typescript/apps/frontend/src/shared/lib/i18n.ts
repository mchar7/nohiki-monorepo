/**
 * i18n configuration using react-i18next with HTTP backend.
 * Production-ready setup with:
 * - Type-safe translations via module augmentation
 * - Namespace organization following Feature-Sliced Design
 * - Browser language detection
 * - Lazy loading of JSON translation files from public/locales
 */

import i18n, { type i18n as I18nInstance } from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import HttpBackend from 'i18next-http-backend';
import { initReactI18next } from 'react-i18next';

const defaultNS = 'common';

const supportedLngs = ['en', 'fr-CA'] as const;

/**
 * All available namespaces following Feature-Sliced Design:
 *
 * Core namespaces:
 * - common: Shared strings (actions, errors, labels, status)
 * - navigation: App-wide navigation
 * - auth: Authentication flows
 * - settings: Settings page
 * - validation: Form validation messages
 * - legal: Terms, privacy policy, licenses
 *
 * Omakase feature namespaces (document generation):
 * Omakase feature namespaces (document generation):
 * - omakase.editor: Document editor feature
 * - omakase.preview: Preview feature
 * - omakase.templateStudio: Template studio feature
 *
 * Platform feature namespaces (job search automation):
 * - dashboard: Main dashboard
 * - jobs: Job listings and matching
 * - profiles: Job target profiles
 * - account: Account settings
 * - attachments: File attachments
 * - documents: Generated documents
 */
const namespaces = [
  'common',
  'navigation',
  'auth',
  'settings',
  'validation',
  'legal',
  'omakase.editor',
  'omakase.preview',
  'omakase.templateStudio',
  'dashboard',
  'jobs',
  'profiles',
  'account',
  'attachments',
  'documents',
] as const;

i18n
  .use(HttpBackend)
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    defaultNS,
    fallbackLng: 'en',
    supportedLngs: [...supportedLngs],
    ns: [...namespaces],

    interpolation: {
      escapeValue: false,
    },

    detection: {
      order: ['localStorage', 'navigator', 'htmlTag'],
      caches: ['localStorage'],
      lookupLocalStorage: 'nohiki-language',
    },

    backend: {
      loadPath: '/locales/{{lng}}/{{ns}}.json',
    },

    react: {
      useSuspense: true,
    },
  });

const i18nInstance: I18nInstance = i18n;

export { i18nInstance as i18n };
