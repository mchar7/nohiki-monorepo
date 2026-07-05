import { describe, expect } from 'vitest';
import { queryClient, queryKeys } from './queryClient.ts';

describe('queryClient - instance', () => {
  test('is a QueryClient instance', () => {
    expect(queryClient).toBeDefined();
    expect(queryClient.getDefaultOptions()).toBeDefined();
  });

  test('has default query options', () => {
    const options = queryClient.getDefaultOptions();
    expect(options.queries).toBeDefined();
    expect(options.queries?.refetchOnWindowFocus).toBe(false);
  });

  test('has mutations set to not retry', () => {
    const options = queryClient.getDefaultOptions();
    expect(options.mutations?.retry).toBe(false);
  });
});

describe('queryKeys - session and account', () => {
  test('has session key', () => {
    expect(queryKeys.session).toEqual(['session']);
  });

  test('has account key', () => {
    expect(queryKeys.account).toEqual(['account']);
  });
});

describe('queryKeys - profiles', () => {
  test('has all profiles key', () => {
    expect(queryKeys.profiles.all).toEqual(['profiles']);
  });

  test('generates list key', () => {
    expect(queryKeys.profiles.list()).toEqual(['profiles', 'list']);
  });

  test('generates detail key with id', () => {
    expect(queryKeys.profiles.detail('123')).toEqual(['profiles', 'detail', '123']);
  });

  test('generates importance key with id', () => {
    expect(queryKeys.profiles.importance('123')).toEqual(['profiles', '123', 'importance']);
  });

  test('generates resolved importance key with id', () => {
    expect(queryKeys.profiles.resolvedImportance('123')).toEqual([
      'profiles',
      '123',
      'resolved-importance',
    ]);
  });
});

describe('queryKeys - listings', () => {
  test('has all listings key', () => {
    expect(queryKeys.listings.all).toEqual(['listings']);
  });

  test('generates list key without filters', () => {
    expect(queryKeys.listings.list()).toEqual(['listings', 'list', undefined]);
  });

  test('generates list key with filters', () => {
    const filters = { status: 'active' };
    expect(queryKeys.listings.list(filters)).toEqual(['listings', 'list', filters]);
  });

  test('generates detail key with id', () => {
    expect(queryKeys.listings.detail('abc')).toEqual(['listings', 'detail', 'abc']);
  });
});

describe('queryKeys - correlations', () => {
  test('has all correlations key', () => {
    expect(queryKeys.correlations.all).toEqual(['correlations']);
  });

  test('generates mine key without filters', () => {
    expect(queryKeys.correlations.mine()).toEqual(['correlations', 'mine', undefined]);
  });

  test('generates mine key with filters', () => {
    const filters = { score: 80 };
    expect(queryKeys.correlations.mine(filters)).toEqual(['correlations', 'mine', filters]);
  });

  test('generates detail key with id', () => {
    expect(queryKeys.correlations.detail('xyz')).toEqual(['correlations', 'detail', 'xyz']);
  });
});

describe('queryKeys - templates', () => {
  test('has all templates key', () => {
    expect(queryKeys.templates.all).toEqual(['templates']);
  });

  test('generates families key', () => {
    expect(queryKeys.templates.families()).toEqual(['templates', 'families']);
  });

  test('generates family key with id', () => {
    expect(queryKeys.templates.family('fam1')).toEqual(['templates', 'families', 'fam1']);
  });

  test('generates versions key', () => {
    expect(queryKeys.templates.versions('fam1')).toEqual([
      'templates',
      'families',
      'fam1',
      'versions',
    ]);
  });

  test('generates version key', () => {
    expect(queryKeys.templates.version('fam1', 2)).toEqual([
      'templates',
      'families',
      'fam1',
      'versions',
      2,
    ]);
  });

  test('generates content key', () => {
    expect(queryKeys.templates.content('fam1', 2)).toEqual([
      'templates',
      'families',
      'fam1',
      'versions',
      2,
      'content',
    ]);
  });
});

describe('queryKeys - schemas', () => {
  test('has all schemas key', () => {
    expect(queryKeys.schemas.all).toEqual(['schemas']);
  });

  test('generates families key', () => {
    expect(queryKeys.schemas.families()).toEqual(['schemas', 'families']);
  });

  test('generates family key with id', () => {
    expect(queryKeys.schemas.family('schema1')).toEqual(['schemas', 'families', 'schema1']);
  });

  test('generates versions key', () => {
    expect(queryKeys.schemas.versions('schema1')).toEqual([
      'schemas',
      'families',
      'schema1',
      'versions',
    ]);
  });
});

describe('queryKeys - documents and attachments', () => {
  test('has all documents key', () => {
    expect(queryKeys.documents.all).toEqual(['documents']);
  });

  test('generates documents list key', () => {
    expect(queryKeys.documents.list()).toEqual(['documents', 'list']);
  });

  test('generates documents status key with requestId', () => {
    expect(queryKeys.documents.status('req123')).toEqual(['documents', 'status', 'req123']);
  });

  test('has all attachments key', () => {
    expect(queryKeys.attachments.all).toEqual(['attachments']);
  });

  test('generates attachments list key', () => {
    expect(queryKeys.attachments.list()).toEqual(['attachments', 'list']);
  });

  test('generates attachments detail key with id', () => {
    expect(queryKeys.attachments.detail('att123')).toEqual(['attachments', 'detail', 'att123']);
  });
});
