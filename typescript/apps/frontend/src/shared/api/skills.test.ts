import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, vi } from 'vitest';
import { hydrateSkillIds, useSkillBatch } from './skills.ts';

const { mockPost, mockUseQuery } = vi.hoisted(() => ({
  mockPost: vi.fn(),
  mockUseQuery: vi.fn(),
}));

vi.mock('@tanstack/react-query', () => ({
  useQuery: (...args: unknown[]) => mockUseQuery(...args),
}));

vi.mock('./client.ts', () => ({
  fetchClient: { POST: mockPost },
  $api: { useQuery: (...args: unknown[]) => mockUseQuery(...args) },
}));

describe('skills api', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('disables batch query when skill list is empty', () => {
    mockUseQuery.mockReturnValue({ enabled: false });

    renderHook(() => useSkillBatch([]));

    expect(mockUseQuery).toHaveBeenCalledWith(
      expect.objectContaining({ enabled: false, queryKey: ['skills', 'batch', []] }),
    );
  });

  test('hydrates skill ids through the batch endpoint', async () => {
    mockPost.mockResolvedValue({
      data: { skills: [{ id: 'skill-1', name: 'TypeScript' }] },
      error: undefined,
    });

    await expect(hydrateSkillIds(['skill-1'])).resolves.toEqual([
      { id: 'skill-1', name: 'TypeScript' },
    ]);

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/api/v1/skills/batch', {
        body: { skill_ids: ['skill-1'] },
      });
    });
  });

  test('splits more than 100 distinct ids into bounded requests and merges results', async () => {
    const skillIds = Array.from({ length: 205 }, (_, index) => `skill-${index.toString()}`);
    mockPost.mockImplementation(
      (_path: string, request: { body: { skill_ids: readonly string[] } }) =>
        Promise.resolve({
          data: {
            skills: request.body.skill_ids.map((id) => ({ id, name: `Name ${id}` })),
          },
          error: undefined,
        }),
    );

    const result = await hydrateSkillIds(skillIds);

    expect(mockPost).toHaveBeenCalledTimes(3);
    expect(mockPost.mock.calls.map((call) => call[1].body.skill_ids)).toEqual([
      skillIds.slice(0, 100),
      skillIds.slice(100, 200),
      skillIds.slice(200),
    ]);
    expect(mockPost.mock.calls.every((call) => call[1].body.skill_ids.length <= 100)).toBe(true);
    expect(result).toHaveLength(205);
    expect(result.map((skill) => skill.id)).toEqual(skillIds);
  });

  test('does not request hydration for an empty id list', async () => {
    await expect(hydrateSkillIds([])).resolves.toEqual([]);

    expect(mockPost).not.toHaveBeenCalled();
  });
});
