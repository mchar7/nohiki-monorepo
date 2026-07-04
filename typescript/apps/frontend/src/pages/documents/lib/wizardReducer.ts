type DocType = 'resume' | 'cover_letter';

interface WizardState {
  step: number;
  docType: DocType | null;
  profileId: string | null;
  matchId: string | null;
  templateId: string | null;
  formData: Record<string, unknown>;
}

type WizardAction =
  | { type: 'SET_DOC_TYPE'; payload: DocType }
  | { type: 'SET_PROFILE'; payload: string }
  | { type: 'SET_MATCH'; payload: string | null }
  | { type: 'SET_TEMPLATE'; payload: string }
  | { type: 'SET_FORM_DATA'; payload: Record<string, unknown> }
  | { type: 'NEXT_STEP' }
  | { type: 'PREV_STEP' }
  | { type: 'RESET' };

const TOTAL_STEPS: number = 5;
const FIRST_STEP: number = 0;
const LAST_STEP: number = TOTAL_STEPS - 1;

const STEP_TYPE: number = 0;
const STEP_PROFILE: number = 1;
const STEP_MATCH: number = 2;
const STEP_TEMPLATE: number = 3;
const STEP_REVIEW: number = 4;

const INITIAL_STATE: WizardState = {
  step: FIRST_STEP,
  docType: null,
  profileId: null,
  matchId: null,
  templateId: null,
  formData: {},
};

/** Checks whether the given step has all required selections to proceed. */
function isStepValid(state: WizardState, step: number): boolean {
  switch (step) {
    case STEP_TYPE:
      return state.docType !== null;
    case STEP_PROFILE:
      return state.profileId !== null;
    case STEP_MATCH:
      return true;
    case STEP_TEMPLATE:
      return state.templateId !== null;
    case STEP_REVIEW:
      return true;
    default:
      return false;
  }
}

function wizardReducer(state: WizardState, action: WizardAction): WizardState {
  switch (action.type) {
    case 'SET_DOC_TYPE':
      return { ...state, docType: action.payload };
    case 'SET_PROFILE':
      return { ...state, profileId: action.payload };
    case 'SET_MATCH':
      return { ...state, matchId: action.payload };
    case 'SET_TEMPLATE':
      return { ...state, templateId: action.payload };
    case 'SET_FORM_DATA':
      return { ...state, formData: action.payload };
    case 'NEXT_STEP': {
      if (!isStepValid(state, state.step)) {
        return state;
      }
      if (state.step >= LAST_STEP) {
        return state;
      }
      return { ...state, step: state.step + 1 };
    }
    case 'PREV_STEP': {
      if (state.step <= FIRST_STEP) {
        return state;
      }
      return { ...state, step: state.step - 1 };
    }
    case 'RESET':
      return { ...INITIAL_STATE };
    default:
      return state;
  }
}

export type { DocType, WizardAction, WizardState };
export {
  FIRST_STEP,
  INITIAL_STATE,
  isStepValid,
  LAST_STEP,
  STEP_MATCH,
  STEP_PROFILE,
  STEP_REVIEW,
  STEP_TEMPLATE,
  STEP_TYPE,
  TOTAL_STEPS,
  wizardReducer,
};
