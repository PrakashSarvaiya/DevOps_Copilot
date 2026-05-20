import { create } from 'zustand';

interface UserProfile {
  id: number;
  username: string;
  email: string;
  role: string;
}

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: UserProfile | null;
  isAuthenticated: boolean;
  setTokens: (access: string, refresh: string) => void;
  setUser: (user: UserProfile) => void;
  login: (access: string, refresh: string, user: UserProfile) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: localStorage.getItem('access_token'),
  refreshToken: localStorage.getItem('refresh_token'),
  user: localStorage.getItem('user_profile') 
    ? JSON.parse(localStorage.getItem('user_profile') || '{}') 
    : null,
  isAuthenticated: !!localStorage.getItem('access_token'),

  setTokens: (access, refresh) => {
    localStorage.setItem('access_token', access);
    localStorage.setItem('refresh_token', refresh);
    set({ accessToken: access, refreshToken: refresh, isAuthenticated: true });
  },

  setUser: (user) => {
    localStorage.setItem('user_profile', JSON.stringify(user));
    set({ user });
  },

  login: (access, refresh, user) => {
    localStorage.setItem('access_token', access);
    localStorage.setItem('refresh_token', refresh);
    localStorage.setItem('user_profile', JSON.stringify(user));
    set({ accessToken: access, refreshToken: refresh, user, isAuthenticated: true });
  },

  logout: () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user_profile');
    set({ accessToken: null, refreshToken: null, user: null, isAuthenticated: false });
  }
}));
