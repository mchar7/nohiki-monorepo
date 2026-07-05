import { describe, expect } from 'vitest';
import { ErrorCodeMap, ErrorMessages, getErrorMessage } from './errors.ts';

/** Minimum password length used to test VALIDATION.MIN_LENGTH message */
const TEST_MIN_PASSWORD_LENGTH: number = 8;
/** Maximum name length used to test VALIDATION.MAX_LENGTH message */
const TEST_MAX_NAME_LENGTH: number = 100;

describe('ErrorMessages', () => {
  test('has auth error messages', () => {
    expect(ErrorMessages.AUTH.INVALID_CREDENTIALS).toBe('Invalid email or password');
    expect(ErrorMessages.AUTH.SESSION_EXPIRED).toBe(
      'Your session has expired. Please login again.',
    );
    expect(ErrorMessages.AUTH.UNAUTHORIZED).toBe('You must be logged in to perform this action');
  });

  test('has profile error messages', () => {
    expect(ErrorMessages.PROFILE.NOT_FOUND).toBe('Profile not found');
    expect(ErrorMessages.PROFILE.DUPLICATE_NAME).toBe('A profile with this name already exists');
  });

  test('has attachment error messages', () => {
    expect(ErrorMessages.ATTACHMENT.NOT_FOUND).toBe('Attachment not found');
    expect(ErrorMessages.ATTACHMENT.FILE_TOO_LARGE).toBe(
      'File size exceeds the maximum limit of 10MB',
    );
  });

  test('has listing error messages', () => {
    expect(ErrorMessages.LISTING.NOT_FOUND).toBe('Job listing not found');
  });

  test('has correlation error messages', () => {
    expect(ErrorMessages.CORRELATION.NOT_FOUND).toBe('Match not found');
  });

  test('has document error messages', () => {
    expect(ErrorMessages.DOCUMENT.TEMPLATE_NOT_FOUND).toBe('Template not found');
    expect(ErrorMessages.DOCUMENT.GENERATION_FAILED).toBe(
      'Document generation failed. Please try again.',
    );
  });

  test('has network error messages', () => {
    expect(ErrorMessages.NETWORK.SERVER_ERROR).toBe('Server error. Please try again later.');
    expect(ErrorMessages.NETWORK.TIMEOUT).toBe('Request timed out. Please try again.');
  });

  test('has validation function for required field', () => {
    expect(ErrorMessages.VALIDATION.REQUIRED_FIELD('Email')).toBe('Email is required');
  });

  test('has validation function for min length', () => {
    expect(ErrorMessages.VALIDATION.MIN_LENGTH('Password', TEST_MIN_PASSWORD_LENGTH)).toBe(
      `Password must be at least ${TEST_MIN_PASSWORD_LENGTH} characters`,
    );
  });

  test('has validation function for max length', () => {
    expect(ErrorMessages.VALIDATION.MAX_LENGTH('Name', TEST_MAX_NAME_LENGTH)).toBe(
      `Name must be at most ${TEST_MAX_NAME_LENGTH} characters`,
    );
  });
});

describe('ErrorCodeMap', () => {
  test('maps auth error codes correctly', () => {
    expect(ErrorCodeMap['AUTH.INVALID_CREDENTIALS']).toBe(ErrorMessages.AUTH.INVALID_CREDENTIALS);
    expect(ErrorCodeMap['AUTH.SESSION_EXPIRED']).toBe(ErrorMessages.AUTH.SESSION_EXPIRED);
    expect(ErrorCodeMap['AUTH.UNAUTHORIZED']).toBe(ErrorMessages.AUTH.UNAUTHORIZED);
    expect(ErrorCodeMap['AUTH.EMAIL_IN_USE']).toBe(ErrorMessages.AUTH.EMAIL_IN_USE);
  });

  test('maps profile error codes correctly', () => {
    expect(ErrorCodeMap['PROFILE.NOT_FOUND']).toBe(ErrorMessages.PROFILE.NOT_FOUND);
    expect(ErrorCodeMap['PROFILE.DUPLICATE_NAME']).toBe(ErrorMessages.PROFILE.DUPLICATE_NAME);
  });

  test('maps attachment error codes correctly', () => {
    expect(ErrorCodeMap['ATTACHMENT.NOT_FOUND']).toBe(ErrorMessages.ATTACHMENT.NOT_FOUND);
    expect(ErrorCodeMap['ATTACHMENT.FILE_TOO_LARGE']).toBe(ErrorMessages.ATTACHMENT.FILE_TOO_LARGE);
  });

  test('maps listing error codes correctly', () => {
    expect(ErrorCodeMap['LISTING.NOT_FOUND']).toBe(ErrorMessages.LISTING.NOT_FOUND);
  });

  test('maps correlation error codes correctly', () => {
    expect(ErrorCodeMap['CORRELATION.NOT_FOUND']).toBe(ErrorMessages.CORRELATION.NOT_FOUND);
  });

  test('maps document error codes correctly', () => {
    expect(ErrorCodeMap['DOCUMENT.TEMPLATE_NOT_FOUND']).toBe(
      ErrorMessages.DOCUMENT.TEMPLATE_NOT_FOUND,
    );
    expect(ErrorCodeMap['DOCUMENT.GENERATION_FAILED']).toBe(
      ErrorMessages.DOCUMENT.GENERATION_FAILED,
    );
  });

  test('maps validation and network error codes correctly', () => {
    expect(ErrorCodeMap['VALIDATION.ERROR']).toBe('Please check your input and try again.');
    expect(ErrorCodeMap['NETWORK.SERVER_ERROR']).toBe(ErrorMessages.NETWORK.SERVER_ERROR);
  });
});

describe('getErrorMessage', () => {
  test('returns correct message for known auth error codes', () => {
    expect(getErrorMessage('AUTH.INVALID_CREDENTIALS')).toBe('Invalid email or password');
    expect(getErrorMessage('AUTH.SESSION_EXPIRED')).toBe(
      'Your session has expired. Please login again.',
    );
  });

  test('returns correct message for known profile error codes', () => {
    expect(getErrorMessage('PROFILE.NOT_FOUND')).toBe('Profile not found');
  });

  test('returns correct message for known attachment error codes', () => {
    expect(getErrorMessage('ATTACHMENT.FILE_TOO_LARGE')).toBe(
      'File size exceeds the maximum limit of 10MB',
    );
  });

  test('returns default server error for unknown codes', () => {
    expect(getErrorMessage('UNKNOWN.CODE')).toBe(ErrorMessages.NETWORK.SERVER_ERROR);
    expect(getErrorMessage('')).toBe(ErrorMessages.NETWORK.SERVER_ERROR);
    expect(getErrorMessage('RANDOM.ERROR.CODE')).toBe(ErrorMessages.NETWORK.SERVER_ERROR);
  });
});
