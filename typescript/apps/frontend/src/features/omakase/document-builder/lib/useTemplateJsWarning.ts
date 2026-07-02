import { useState } from 'react';
import { useDocumentBuilderStore } from '../model/index.ts';
import { shouldShowJsWarning } from './jsDetector.ts';

type RenderMethod = 'html' | 'image';

interface TemplateInfo {
  id: string;
  displayName?: string;
  version?: string;
  requiresJavaScript?: {
    required: boolean;
    reason?: string;
  };
}

interface UseTemplateJsWarningReturn {
  showWarning: boolean;
  templateName: string;
  templateVersion: string;
  reason?: string | undefined;
  checkJsRequirement: (templateId?: string, htmlTemplate?: string) => boolean;
  handleJsChoice: (method: RenderMethod, remember: boolean) => void;
  closeWarning: () => void;
}

// Session-based storage for template render preferences (not persisted)
const sessionTemplatePrefs: Map<string, RenderMethod> = new Map<string, RenderMethod>();

function getSessionPref(templateId: string, version: string): RenderMethod | null {
  const key = `${templateId}@${version}`;
  return sessionTemplatePrefs.get(key) || null;
}

function setSessionPref(templateId: string, version: string, method: RenderMethod): void {
  const key = `${templateId}@${version}`;
  sessionTemplatePrefs.set(key, method);
}

/** Determines if JS is required based on template metadata and/or content detection. */
function checkJsRequirements(
  tmpl: TemplateInfo,
  htmlTemplate?: string,
): { isDeclared: boolean; requiresJs: boolean; reason?: string } {
  const isDeclared = tmpl.requiresJavaScript?.required === true;
  const isDetected: boolean = htmlTemplate ? shouldShowJsWarning(htmlTemplate) : false;
  return {
    isDeclared,
    requiresJs: isDeclared || isDetected,
    reason: tmpl.requiresJavaScript?.reason,
  };
}

/** Checks permanent and session render preferences for a template. */
function checkSavedPreferences(
  tmpl: TemplateInfo,
  getStoredPref: (id: string, version: string) => RenderMethod | null,
): { found: boolean; method: RenderMethod | null } {
  const version = tmpl.version ?? '1.0';
  const savedPref = getStoredPref(tmpl.id, version);
  if (savedPref) {
    return { found: true, method: savedPref };
  }
  const sessionPref = getSessionPref(tmpl.id, version);
  if (sessionPref) {
    return { found: true, method: sessionPref };
  }
  return { found: false, method: null };
}

/** Builds the reason string for the JS warning dialog. */
function buildWarningReason(isDeclared: boolean, jsReason?: string): string {
  if (isDeclared) {
    return jsReason
      ? `This template explicitly declares that it requires JavaScript execution: ${jsReason}.`
      : 'This template explicitly declares that it requires JavaScript execution.';
  }
  return 'JavaScript code was detected in this template.';
}

interface WarningDisplayState {
  templateName: string;
  templateVersion: string;
  reason: string | undefined;
}

interface CheckJsContext {
  template: TemplateInfo;
  getTemplateRenderPref: (id: string, version: string) => RenderMethod | null;
  onRenderChoice?: (method: RenderMethod) => void;
}

/** Evaluates JS requirements and saved preferences; returns warning state if needed. */
function evaluateJsRequirement(
  htmlTemplate: string | undefined,
  ctx: CheckJsContext,
): WarningDisplayState | null {
  const jsReqs = checkJsRequirements(ctx.template, htmlTemplate);
  if (!jsReqs.requiresJs) {
    return null;
  }
  const preference = checkSavedPreferences(ctx.template, ctx.getTemplateRenderPref);
  if (preference.found && preference.method) {
    ctx.onRenderChoice?.(preference.method);
    return null;
  }
  return {
    templateName: ctx.template.displayName || 'Unavailable',
    templateVersion: ctx.template.version ?? '1.0',
    reason: buildWarningReason(jsReqs.isDeclared, jsReqs.reason),
  };
}

function useTemplateJsWarning(
  templateId?: string,
  onRenderChoice?: (method: RenderMethod) => void,
): UseTemplateJsWarningReturn {
  const [showWarning, setShowWarning] = useState(false);
  const currentTemplate = useDocumentBuilderStore((state) => state.currentTemplate);
  const getTemplateRenderPref = useDocumentBuilderStore((state) => state.getTemplateRenderPref);
  const setTemplateRenderPref = useDocumentBuilderStore((state) => state.setTemplateRenderPref);
  const [displayState, setDisplayState] = useState<WarningDisplayState>({
    templateName: '',
    templateVersion: '1.0',
    reason: undefined,
  });

  const template: TemplateInfo | undefined = (() => {
    if (!currentTemplate || (templateId && currentTemplate.id !== templateId)) {
      return;
    }
    return {
      id: currentTemplate.id,
      displayName: currentTemplate.display_name,
      version: currentTemplate.version,
    };
  })();

  const checkJsRequirement = (_id?: string, htmlTemplate?: string) => {
    if (!template) {
      return false;
    }
    const warning = evaluateJsRequirement(htmlTemplate, {
      template,
      getTemplateRenderPref,
      onRenderChoice,
    });
    if (!warning) {
      return false;
    }
    setShowWarning(true);
    setDisplayState(warning);
    return true;
  };

  const handleJsChoice = (method: RenderMethod, remember: boolean) => {
    if (!template) {
      return;
    }
    const version = template.version || '1.0';
    if (remember) {
      setTemplateRenderPref(template.id, version, method);
    } else {
      setSessionPref(template.id, version, method);
    }
    onRenderChoice?.(method);
    setShowWarning(false);
  };

  return {
    showWarning,
    ...displayState,
    checkJsRequirement,
    handleJsChoice,
    closeWarning: () => setShowWarning(false),
  };
}

export type { RenderMethod, UseTemplateJsWarningReturn };
export { useTemplateJsWarning };
