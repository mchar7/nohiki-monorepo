import {
  Briefcase,
  FileText,
  Home,
  LayoutTemplate,
  type LucideIcon,
  Plus,
  Search,
  Settings,
  Sparkles,
  Star,
  User,
} from 'lucide-react';
import { ROUTE_PATHS } from './routes.ts';

export type NavigationTitleKey =
  | 'sidebar.dashboard'
  | 'sidebar.jobs.title'
  | 'sidebar.jobs.browse'
  | 'sidebar.jobs.matches'
  | 'sidebar.profiles.title'
  | 'sidebar.profiles.list'
  | 'sidebar.profiles.create'
  | 'sidebar.documents.title'
  | 'sidebar.documents.list'
  | 'sidebar.documents.generate'
  | 'sidebar.documents.templates'
  | 'sidebar.account'
  | 'sidebar.settings';

export interface NavItem {
  readonly titleKey: NavigationTitleKey;
  readonly icon: LucideIcon;
  readonly href?: string;
  readonly end?: boolean;
  readonly children?: readonly NavItem[];
  readonly badge?: number;
}

/**
 * Main navigation items for the sidebar.
 *
 * Documents section expands to show sub-items: My Documents, Generate, Templates.
 */
export const MAIN_NAVIGATION: readonly NavItem[] = [
  {
    titleKey: 'sidebar.dashboard',
    icon: Home,
    href: ROUTE_PATHS.HOME,
    end: true,
  },
  {
    titleKey: 'sidebar.jobs.title',
    icon: Briefcase,
    children: [
      { titleKey: 'sidebar.jobs.browse', icon: Search, href: ROUTE_PATHS.JOBS.LIST },
      { titleKey: 'sidebar.jobs.matches', icon: Star, href: ROUTE_PATHS.JOBS.MATCHES },
    ],
  },
  {
    titleKey: 'sidebar.profiles.title',
    icon: User,
    children: [
      { titleKey: 'sidebar.profiles.list', icon: User, href: ROUTE_PATHS.PROFILES.LIST },
      { titleKey: 'sidebar.profiles.create', icon: Plus, href: ROUTE_PATHS.PROFILES.NEW },
    ],
  },
  {
    titleKey: 'sidebar.documents.title',
    icon: FileText,
    children: [
      { titleKey: 'sidebar.documents.list', icon: FileText, href: ROUTE_PATHS.DOCUMENTS.LIST },
      {
        titleKey: 'sidebar.documents.generate',
        icon: Sparkles,
        href: ROUTE_PATHS.DOCUMENTS.GENERATE,
      },
      {
        titleKey: 'sidebar.documents.templates',
        icon: LayoutTemplate,
        href: ROUTE_PATHS.DOCUMENTS.TEMPLATES,
      },
    ],
  },
  {
    titleKey: 'sidebar.account',
    icon: User,
    href: ROUTE_PATHS.ACCOUNT.SETTINGS,
  },
  {
    titleKey: 'sidebar.settings',
    icon: Settings,
    href: ROUTE_PATHS.SETTINGS,
  },
] as const;
