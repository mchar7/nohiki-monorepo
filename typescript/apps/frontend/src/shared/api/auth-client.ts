import { fetchClient } from './client.ts';
import type {
  CreateUserRequest,
  LoginRequest,
  LoginResponse,
  SessionResponse,
  UserCreateResponse,
} from './types.ts';

/**
 * Auth API facade using openapi-fetch.
 *
 * All auth endpoints go through Traefik to user-auth-service.
 * Session endpoint goes through Traefik to bff-service.
 *
 * Authentication uses HttpOnly cookies - tokens are NOT in response body.
 */
export const authApi = {
  login: async (credentials: LoginRequest): Promise<LoginResponse> => {
    const { data, error } = await fetchClient.POST('/api/v1/auth/login', {
      body: credentials,
    });
    if (error) {
      throw error;
    }
    return data;
  },

  register: async (body: CreateUserRequest): Promise<UserCreateResponse> => {
    const { data, error } = await fetchClient.POST('/api/v1/auth/register', {
      body,
    });
    if (error) {
      throw error;
    }
    return data;
  },

  logout: async (): Promise<void> => {
    const { error } = await fetchClient.POST('/api/v1/auth/logout');
    if (error) {
      throw error;
    }
  },

  refresh: async (): Promise<void> => {
    const { error } = await fetchClient.POST('/api/v1/auth/refresh');
    if (error) {
      throw error;
    }
  },

  getSession: async (): Promise<SessionResponse> => {
    const { data, error } = await fetchClient.GET('/api/v1/session');
    if (error) {
      throw error;
    }
    return data;
  },
} as const;
