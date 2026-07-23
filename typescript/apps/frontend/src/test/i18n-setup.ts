import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';
import accountEn from '../../public/locales/en/account.json' with { type: 'json' };
import attachmentsEn from '../../public/locales/en/attachments.json' with { type: 'json' };
import authEn from '../../public/locales/en/auth.json' with { type: 'json' };
import commonEn from '../../public/locales/en/common.json' with { type: 'json' };
import dashboardEn from '../../public/locales/en/dashboard.json' with { type: 'json' };
import documentsEn from '../../public/locales/en/documents.json' with { type: 'json' };
import jobsEn from '../../public/locales/en/jobs.json' with { type: 'json' };
import legalEn from '../../public/locales/en/legal.json' with { type: 'json' };
import navigationEn from '../../public/locales/en/navigation.json' with { type: 'json' };
import omakaseEditorEn from '../../public/locales/en/omakase.editor.json' with { type: 'json' };
import omakasePreviewEn from '../../public/locales/en/omakase.preview.json' with { type: 'json' };
import omakaseTemplateStudioEn from '../../public/locales/en/omakase.templateStudio.json' with {
  type: 'json',
};
import profilesEn from '../../public/locales/en/profiles.json' with { type: 'json' };
import settingsEn from '../../public/locales/en/settings.json' with { type: 'json' };

const i18n: ReturnType<typeof i18next.createInstance> = i18next.createInstance();

i18n.use(initReactI18next).init({
  lng: 'en',
  fallbackLng: 'en',
  ns: [
    'common',
    'auth',
    'navigation',
    'settings',
    'legal',
    'omakase.editor',
    'omakase.preview',
    'omakase.templateStudio',
    'dashboard',
    'account',
    'attachments',
    'documents',
    'jobs',
    'profiles',
  ],
  defaultNS: 'common',
  resources: {
    en: {
      common: commonEn,
      auth: authEn,
      navigation: navigationEn,
      settings: settingsEn,
      legal: legalEn,
      'omakase.editor': omakaseEditorEn,
      'omakase.preview': omakasePreviewEn,
      'omakase.templateStudio': omakaseTemplateStudioEn,
      dashboard: dashboardEn,
      account: accountEn,
      attachments: attachmentsEn,
      documents: documentsEn,
      jobs: jobsEn,
      profiles: profilesEn,
    },
  },
  interpolation: {
    escapeValue: false,
  },
  react: {
    useSuspense: false,
  },
});

export { i18n };
