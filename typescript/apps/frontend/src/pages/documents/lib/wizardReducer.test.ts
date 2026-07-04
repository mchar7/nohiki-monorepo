import { describe, expect } from 'vitest';
import type { WizardState } from './wizardReducer.ts';
import {
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
} from './wizardReducer.ts';

describe('wizardReducer - INITIAL_STATE', () => {
  test('starts at step 0 with all selections null', () => {
    expect(INITIAL_STATE.step).toBe(FIRST_STEP);
    expect(INITIAL_STATE.docType).toBeNull();
    expect(INITIAL_STATE.profileId).toBeNull();
    expect(INITIAL_STATE.matchId).toBeNull();
    expect(INITIAL_STATE.templateId).toBeNull();
    expect(INITIAL_STATE.formData).toEqual({});
  });
});

describe('wizardReducer - SET actions', () => {
  test('SET_DOC_TYPE sets the document type', () => {
    const result = wizardReducer(INITIAL_STATE, { type: 'SET_DOC_TYPE', payload: 'resume' });
    expect(result.docType).toBe('resume');
  });

  test('SET_DOC_TYPE can switch between types', () => {
    const withResume = wizardReducer(INITIAL_STATE, { type: 'SET_DOC_TYPE', payload: 'resume' });
    const result = wizardReducer(withResume, { type: 'SET_DOC_TYPE', payload: 'cover_letter' });
    expect(result.docType).toBe('cover_letter');
  });

  test('SET_PROFILE sets the profile ID', () => {
    const result = wizardReducer(INITIAL_STATE, { type: 'SET_PROFILE', payload: 'prof-1' });
    expect(result.profileId).toBe('prof-1');
  });

  test('SET_MATCH sets the match ID', () => {
    const result = wizardReducer(INITIAL_STATE, { type: 'SET_MATCH', payload: 'match-1' });
    expect(result.matchId).toBe('match-1');
  });

  test('SET_MATCH allows null to skip matching', () => {
    const withMatch = wizardReducer(INITIAL_STATE, { type: 'SET_MATCH', payload: 'match-1' });
    const result = wizardReducer(withMatch, { type: 'SET_MATCH', payload: null });
    expect(result.matchId).toBeNull();
  });

  test('SET_TEMPLATE sets the template ID', () => {
    const result = wizardReducer(INITIAL_STATE, { type: 'SET_TEMPLATE', payload: 'tpl-1' });
    expect(result.templateId).toBe('tpl-1');
  });

  test('SET_FORM_DATA sets and replaces form data', () => {
    const first = wizardReducer(INITIAL_STATE, { type: 'SET_FORM_DATA', payload: { a: 1 } });
    expect(first.formData).toEqual({ a: 1 });
    const second = wizardReducer(first, { type: 'SET_FORM_DATA', payload: { b: 2 } });
    expect(second.formData).toEqual({ b: 2 });
  });
});

describe('wizardReducer - NEXT_STEP', () => {
  test('advances when current step is valid', () => {
    const withType = wizardReducer(INITIAL_STATE, { type: 'SET_DOC_TYPE', payload: 'resume' });
    const result = wizardReducer(withType, { type: 'NEXT_STEP' });
    expect(result.step).toBe(STEP_PROFILE);
  });

  test('does not advance when current step is invalid', () => {
    const result = wizardReducer(INITIAL_STATE, { type: 'NEXT_STEP' });
    expect(result.step).toBe(STEP_TYPE);
  });

  test('does not advance past the last step', () => {
    const atLast: WizardState = {
      ...INITIAL_STATE,
      step: LAST_STEP,
      docType: 'resume',
      profileId: 'p',
      templateId: 't',
    };
    const result = wizardReducer(atLast, { type: 'NEXT_STEP' });
    expect(result.step).toBe(LAST_STEP);
  });

  test('preserves all selections when advancing', () => {
    let state = wizardReducer(INITIAL_STATE, { type: 'SET_DOC_TYPE', payload: 'resume' });
    state = wizardReducer(state, { type: 'NEXT_STEP' });
    state = wizardReducer(state, { type: 'SET_PROFILE', payload: 'prof-1' });
    state = wizardReducer(state, { type: 'NEXT_STEP' });
    expect(state.step).toBe(STEP_MATCH);
    expect(state.docType).toBe('resume');
    expect(state.profileId).toBe('prof-1');
  });
});

describe('wizardReducer - PREV_STEP', () => {
  test('goes back one step', () => {
    const atStep1: WizardState = { ...INITIAL_STATE, step: STEP_PROFILE, docType: 'resume' };
    const result = wizardReducer(atStep1, { type: 'PREV_STEP' });
    expect(result.step).toBe(STEP_TYPE);
  });

  test('does not go before step 0', () => {
    const result = wizardReducer(INITIAL_STATE, { type: 'PREV_STEP' });
    expect(result.step).toBe(STEP_TYPE);
  });

  test('preserves selections when going back', () => {
    const state: WizardState = {
      ...INITIAL_STATE,
      step: STEP_TEMPLATE,
      docType: 'cover_letter',
      profileId: 'prof-1',
      matchId: 'match-1',
    };
    const result = wizardReducer(state, { type: 'PREV_STEP' });
    expect(result.step).toBe(STEP_MATCH);
    expect(result.docType).toBe('cover_letter');
    expect(result.profileId).toBe('prof-1');
    expect(result.matchId).toBe('match-1');
  });
});

describe('wizardReducer - RESET', () => {
  test('returns to initial state', () => {
    const modified: WizardState = {
      step: STEP_TEMPLATE,
      docType: 'resume',
      profileId: 'prof-1',
      matchId: 'match-1',
      templateId: 'tpl-1',
      formData: { key: 'value' },
    };
    const result = wizardReducer(modified, { type: 'RESET' });
    expect(result).toEqual(INITIAL_STATE);
  });
});

describe('isStepValid', () => {
  test('step 0 requires docType', () => {
    expect(isStepValid(INITIAL_STATE, STEP_TYPE)).toBe(false);
    expect(isStepValid({ ...INITIAL_STATE, docType: 'resume' }, STEP_TYPE)).toBe(true);
  });

  test('step 1 requires profileId', () => {
    expect(isStepValid(INITIAL_STATE, STEP_PROFILE)).toBe(false);
    expect(isStepValid({ ...INITIAL_STATE, profileId: 'p-1' }, STEP_PROFILE)).toBe(true);
  });

  test('step 2 is always valid (match is optional)', () => {
    expect(isStepValid(INITIAL_STATE, STEP_MATCH)).toBe(true);
    expect(isStepValid({ ...INITIAL_STATE, matchId: 'match-1' }, STEP_MATCH)).toBe(true);
  });

  test('step 3 requires templateId', () => {
    expect(isStepValid(INITIAL_STATE, STEP_TEMPLATE)).toBe(false);
    expect(isStepValid({ ...INITIAL_STATE, templateId: 't-1' }, STEP_TEMPLATE)).toBe(true);
  });

  test('step 4 (review) is always valid', () => {
    expect(isStepValid(INITIAL_STATE, STEP_REVIEW)).toBe(true);
  });

  test('returns false for out-of-range steps', () => {
    expect(isStepValid(INITIAL_STATE, -1)).toBe(false);
    expect(isStepValid(INITIAL_STATE, TOTAL_STEPS)).toBe(false);
  });
});

describe('step transition flow', () => {
  test('completes a full wizard flow', () => {
    let state = INITIAL_STATE;
    state = wizardReducer(state, { type: 'SET_DOC_TYPE', payload: 'resume' });
    state = wizardReducer(state, { type: 'NEXT_STEP' });
    expect(state.step).toBe(STEP_PROFILE);
    state = wizardReducer(state, { type: 'SET_PROFILE', payload: 'prof-1' });
    state = wizardReducer(state, { type: 'NEXT_STEP' });
    expect(state.step).toBe(STEP_MATCH);
    state = wizardReducer(state, { type: 'NEXT_STEP' });
    expect(state.step).toBe(STEP_TEMPLATE);
    state = wizardReducer(state, { type: 'SET_TEMPLATE', payload: 'tpl-1' });
    state = wizardReducer(state, { type: 'NEXT_STEP' });
    expect(state.step).toBe(STEP_REVIEW);
    expect(state.docType).toBe('resume');
    expect(state.profileId).toBe('prof-1');
    expect(state.matchId).toBeNull();
    expect(state.templateId).toBe('tpl-1');
  });

  test('blocks advancement if required fields are missing', () => {
    let state = INITIAL_STATE;
    state = wizardReducer(state, { type: 'NEXT_STEP' });
    expect(state.step).toBe(STEP_TYPE);
    state = wizardReducer(state, { type: 'SET_DOC_TYPE', payload: 'cover_letter' });
    state = wizardReducer(state, { type: 'NEXT_STEP' });
    expect(state.step).toBe(STEP_PROFILE);
    state = wizardReducer(state, { type: 'NEXT_STEP' });
    expect(state.step).toBe(STEP_PROFILE);
  });
});
