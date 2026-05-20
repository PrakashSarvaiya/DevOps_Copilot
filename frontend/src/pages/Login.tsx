import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Terminal, Shield, ArrowRight, UserPlus, Lock } from 'lucide-react';
import { api } from '../services/api';
import { useAuthStore } from '../store/auth_store';

function getApiErrorMessage(error: unknown, fallback: string) {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: unknown } } }).response;
    if (typeof response?.data?.detail === 'string') {
      return response.data.detail;
    }
  }

  return fallback;
}

export default function Login() {
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const navigate = useNavigate();
  const loginStore = useAuthStore((state) => state.login);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      if (isRegister) {
        // Register API call
        const regRes = await api.post('/auth/register', { username, email, password, role: 'DevOps Engineer' });
        const { access_token, refresh_token } = regRes.data;
        
        // Fetch user info
        const meRes = await api.get('/auth/me', {
          headers: { Authorization: `Bearer ${access_token}` }
        });
        loginStore(access_token, refresh_token, meRes.data);
      } else {
        // Login API call
        const logRes = await api.post('/auth/login', { username, password });
        const { access_token, refresh_token } = logRes.data;

        // Fetch user info
        const meRes = await api.get('/auth/me', {
          headers: { Authorization: `Bearer ${access_token}` }
        });
        loginStore(access_token, refresh_token, meRes.data);
      }
      navigate('/dashboard');
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, 'Authentication failed. Please verify credentials.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center relative px-4 bg-[#070913]">
      {/* Background glowing blobs */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-indigo-600/10 rounded-full blur-[100px] pointer-events-none"></div>
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-cyan-600/10 rounded-full blur-[100px] pointer-events-none"></div>

      <div className="w-full max-w-md glass-card rounded-2xl p-8 border border-white/5 relative z-10">
        {/* Brand Header */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/20 mb-4 animate-pulse">
            <Terminal className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-3xl font-extrabold font-outfit bg-clip-text text-transparent bg-gradient-to-r from-white via-slate-200 to-cyan-400 tracking-tight text-glow-cyan">
            DVOPS Copilot
          </h1>
          <p className="text-slate-400 text-sm mt-2 text-center">
            AI-powered troubleshooting & deployment platform
          </p>
        </div>

        {error && (
          <div className="mb-6 p-3 rounded-lg bg-rose-500/15 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
            <Shield className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">Username</label>
            <div className="relative">
              <Terminal className="absolute left-3 top-3.5 w-4 h-4 text-slate-400" />
              <input
                type="text"
                required
                className="w-full pl-10 pr-4 py-3 glass-input text-sm"
                placeholder="e.g. devops_hero"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>
          </div>

          {isRegister && (
            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">Email Address</label>
              <div className="relative">
                <UserPlus className="absolute left-3 top-3.5 w-4 h-4 text-slate-400" />
                <input
                  type="email"
                  required
                  className="w-full pl-10 pr-4 py-3 glass-input text-sm"
                  placeholder="name@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">Password</label>
            <div className="relative">
              <Lock className="absolute left-3 top-3.5 w-4 h-4 text-slate-400" />
              <input
                type="password"
                required
                className="w-full pl-10 pr-4 py-3 glass-input text-sm"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-gradient-to-r from-indigo-600 to-cyan-500 hover:from-indigo-500 hover:to-cyan-400 text-white font-medium py-3 rounded-lg shadow-lg shadow-indigo-600/20 flex items-center justify-center gap-2 glow-btn mt-6 text-sm disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
          >
            <span>{loading ? 'Authenticating...' : (isRegister ? 'Create Account' : 'Authenticate')}</span>
            {!loading && <ArrowRight className="w-4 h-4" />}
          </button>
        </form>

        <div className="mt-8 text-center text-xs text-slate-400">
          {isRegister ? (
            <span>
              Already have an account?{' '}
              <button onClick={() => { setIsRegister(false); setError(''); }} className="text-cyan-400 hover:underline font-semibold cursor-pointer">
                Sign In
              </button>
            </span>
          ) : (
            <span>
              Need access?{' '}
              <button onClick={() => { setIsRegister(true); setError(''); }} className="text-cyan-400 hover:underline font-semibold cursor-pointer">
                Register DevOps Profile
              </button>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
