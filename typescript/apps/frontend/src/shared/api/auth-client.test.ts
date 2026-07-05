import { beforeEach, describe, expect, vi } from 'vitest';

const {
  mockGet,
  mockPost,
}: {
  mockGet: ReturnType<typeof vi.fn>;
  mockPost: ReturnType<typeof vi.fn>;
} = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
}));

vi.mock('@/shared/api/client', () => ({
  fetchClient: { GET: mockGet, POST: mockPost, DELETE: vi.fn(), PATCH: vi.fn(), PUT: vi.fn() },
  $api: { useQuery: vi.fn(), useMutation: vi.fn() },
  createDevClient: vi.fn(),
}));

import { authApi } from './auth-client.ts';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('authApi login', () => {
  test('calls fetchClient.POST with login path and body', async () => {
    const credentials = { email: 'user@example.com', password: 'secret' };
    const expected = { user_id: 'abc-123', email: 'user@example.com' };
    mockPost.mockResolvedValue({ data: expected, error: undefined });

    const result = await authApi.login(credentials);

    expect(mockPost).toHaveBeenCalledWith('/api/v1/auth/login', { body: credentials });
    expect(result).toEqual(expected);
  });
});

describe('authApi register', () => {
  test('posts the generated CreateUserRequest shape with canonical display name only', async () => {
    const data = {
      email: 'new@example.com',
      password: 'password',
      display_name: '李 小龍',
    };
    const expected = { id: 'user-new', email: 'new@example.com', message: 'created' };
    mockPost.mockResolvedValue({ data: expected, error: undefined });

    const result = await authApi.register(data);

    expect(mockPost).toHaveBeenCalledWith('/api/v1/auth/register', { body: data });
    expect(mockPost.mock.calls[0]?.[1]?.body).not.toHaveProperty('first_name');
    expect(mockPost.mock.calls[0]?.[1]?.body).not.toHaveProperty('last_name');
    expect(result).toEqual(expected);
  });
});

describe('authApi logout', () => {
  test('calls fetchClient.POST with logout path', async () => {
    mockPost.mockResolvedValue({ data: undefined, error: undefined });

    await authApi.logout();

    expect(mockPost).toHaveBeenCalledWith('/api/v1/auth/logout');
  });
});

describe('authApi refresh', () => {
  test('calls fetchClient.POST with refresh path', async () => {
    mockPost.mockResolvedValue({ data: undefined, error: undefined });

    await authApi.refresh();

    expect(mockPost).toHaveBeenCalledWith('/api/v1/auth/refresh');
  });
});

describe('authApi getSession', () => {
  test('calls fetchClient.GET with session path', async () => {
    const expected = { user_id: 'user-123', roles: ['user'], permissions: [] };
    mockGet.mockResolvedValue({ data: expected, error: undefined });

    const result = await authApi.getSession();

    expect(mockGet).toHaveBeenCalledWith('/api/v1/session');
    expect(result).toEqual(expected);
  });
});
