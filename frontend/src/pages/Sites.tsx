import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Globe,
  Plus,
  RefreshCcw,
  Trash2,
  ExternalLink,
  CheckCircle2,
  XCircle,
  HelpCircle,
  Clock,
  Settings,
  ChevronDown,
  X,
} from 'lucide-react';
import { api } from '../services/api';

const AUTO_REFRESH_MS = 30_000;

interface Site {
  id: number;
  user_id: number;
  name: string;
  url: string;
  check_interval_seconds: number;
  timeout_seconds: number;
  enabled: boolean;
  additional_ok_codes: string;
  last_checked_at: string | null;
  last_status: 'UP' | 'DOWN' | 'UNKNOWN' | string;
  last_response_ms: number | null;
  last_error: string | null;
  last_status_changed_at: string | null;
  created_at: string;
}

function getApiErrorMessage(error: unknown, fallback: string) {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: unknown } } }).response;
    if (typeof response?.data?.detail === 'string') {
      return response.data.detail;
    }
  }
  return fallback;
}

function relativeTime(iso: string | null, now: number): string {
  if (!iso) return 'never';
  const t = new Date(iso).getTime();
  const secs = Math.max(0, Math.round((now - t) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}

function downtimeLabel(site: Site, now: number): string | null {
  if (site.last_status !== 'DOWN' || !site.last_status_changed_at) return null;
  const t = new Date(site.last_status_changed_at).getTime();
  const secs = Math.max(0, Math.round((now - t) / 1000));
  if (secs < 60) return `down for ${secs}s`;
  if (secs < 3600) return `down for ${Math.round(secs / 60)}m`;
  if (secs < 86400) return `down for ${Math.round(secs / 3600)}h`;
  return `down for ${Math.round(secs / 86400)}d`;
}

function StatusPill({ status }: { status: string }) {
  if (status === 'UP') {
    return (
      <span className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-emerald-500/25 bg-emerald-500/10 text-emerald-300 text-[10px] font-semibold uppercase tracking-wider">
        <CheckCircle2 className="w-3 h-3" />
        UP
      </span>
    );
  }
  if (status === 'DOWN') {
    return (
      <span className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-rose-500/30 bg-rose-500/10 text-rose-300 text-[10px] font-semibold uppercase tracking-wider">
        <XCircle className="w-3 h-3 animate-pulse" />
        DOWN
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-slate-500/25 bg-slate-500/10 text-slate-300 text-[10px] font-semibold uppercase tracking-wider">
      <HelpCircle className="w-3 h-3" />
      {status}
    </span>
  );
}

interface FormState {
  name: string;
  url: string;
  check_interval_seconds: string;
  timeout_seconds: string;
  additional_ok_codes: string;
  enabled: boolean;
}

const EMPTY_FORM: FormState = {
  name: '',
  url: '',
  check_interval_seconds: '60',
  timeout_seconds: '10',
  additional_ok_codes: '',
  enabled: true,
};

export default function Sites() {
  const [sites, setSites] = useState<Site[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Modal state — `mode` controls which modal (if any) is open; null is closed.
  // `editId` is set when editing an existing site; null on add.
  const [mode, setMode] = useState<'add' | 'edit' | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [checkingId, setCheckingId] = useState<number | null>(null);
  const [now, setNow] = useState<number>(Date.now());
  const refreshRef = useRef<(() => Promise<void>) | undefined>(undefined);

  const openAdd = () => {
    setMode('add');
    setEditId(null);
    setForm(EMPTY_FORM);
    setShowAdvanced(false);
    setFormError(null);
  };

  const openEdit = (site: Site) => {
    setMode('edit');
    setEditId(site.id);
    setForm({
      name: site.name,
      url: site.url,
      check_interval_seconds: String(site.check_interval_seconds),
      timeout_seconds: String(site.timeout_seconds),
      additional_ok_codes: site.additional_ok_codes ?? '',
      enabled: site.enabled,
    });
    setShowAdvanced(true); // people usually open Edit because they want the knobs
    setFormError(null);
  };

  const closeModal = () => {
    setMode(null);
    setEditId(null);
    setFormError(null);
  };

  const refresh = useCallback(async () => {
    try {
      const res = await api.get<Site[]>('/sites/');
      setSites(res.data);
      setError(null);
    } catch (err) {
      console.error(err);
      setError(getApiErrorMessage(err, 'Failed to load sites.'));
    } finally {
      setLoading(false);
    }
  }, []);
  refreshRef.current = refresh;

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => {
      void refreshRef.current?.();
    }, AUTO_REFRESH_MS);
    const clock = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      window.clearInterval(id);
      window.clearInterval(clock);
    };
  }, [refresh]);

  const stats = useMemo(() => {
    let up = 0,
      down = 0,
      unknown = 0;
    for (const s of sites) {
      if (s.last_status === 'UP') up++;
      else if (s.last_status === 'DOWN') down++;
      else unknown++;
    }
    return { total: sites.length, up, down, unknown };
  }, [sites]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    setSubmitting(true);
    const payload: Record<string, unknown> = {
      name: form.name.trim(),
      url: form.url.trim(),
      additional_ok_codes: form.additional_ok_codes.trim(),
    };
    const interval = parseInt(form.check_interval_seconds, 10);
    const timeout = parseInt(form.timeout_seconds, 10);
    if (!Number.isNaN(interval)) payload.check_interval_seconds = interval;
    if (!Number.isNaN(timeout)) payload.timeout_seconds = timeout;
    if (mode === 'edit') payload.enabled = form.enabled;
    try {
      if (mode === 'edit' && editId != null) {
        await api.put(`/sites/${editId}`, payload);
      } else {
        await api.post('/sites/', payload);
      }
      closeModal();
      await refresh();
    } catch (err) {
      setFormError(
        getApiErrorMessage(err, mode === 'edit' ? 'Failed to update site.' : 'Failed to add site.'),
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (site: Site) => {
    if (!window.confirm(`Stop monitoring "${site.name}"?`)) return;
    try {
      await api.delete(`/sites/${site.id}`);
      setSites((prev) => prev.filter((s) => s.id !== site.id));
    } catch (err) {
      alert(getApiErrorMessage(err, 'Failed to delete site.'));
    }
  };

  const handleCheck = async (site: Site) => {
    setCheckingId(site.id);
    try {
      await api.post(`/sites/${site.id}/check`);
      await refresh();
    } catch (err) {
      alert(getApiErrorMessage(err, 'Failed to check site.'));
    } finally {
      setCheckingId(null);
    }
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="glass-card p-6 rounded-2xl border border-white/5 flex items-center gap-6">
        <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-cyan-500 to-emerald-400 flex items-center justify-center shadow-lg shadow-cyan-500/20 shrink-0">
          <Globe className="w-7 h-7 text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="font-outfit font-extrabold text-xl text-slate-100">Site Monitor</h2>
          <p className="text-sm text-slate-400 mt-1">
            Watches the URLs you register. Pings each one on its own interval. Emails DevOps the first time a site flips to DOWN — no spam after that.
          </p>
        </div>
        <button
          onClick={openAdd}
          className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-emerald-500 hover:from-cyan-400 hover:to-emerald-400 text-slate-900 font-semibold text-sm rounded-lg shadow-lg shadow-cyan-500/20 transition-colors cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          Add site
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { name: 'Monitored', value: stats.total, tone: 'text-indigo-300 bg-indigo-500/10 border-indigo-500/20', icon: Globe },
          { name: 'Up', value: stats.up, tone: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20', icon: CheckCircle2 },
          { name: 'Down', value: stats.down, tone: 'text-rose-300 bg-rose-500/10 border-rose-500/20', icon: XCircle },
          { name: 'Unknown', value: stats.unknown, tone: 'text-slate-300 bg-slate-500/10 border-slate-500/20', icon: HelpCircle },
        ].map((card) => {
          const Icon = card.icon;
          return (
            <div
              key={card.name}
              className={`glass-card p-4 rounded-2xl border flex items-center justify-between ${card.tone}`}
            >
              <div className="min-w-0">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 truncate">
                  {card.name}
                </p>
                <p className="text-2xl font-extrabold font-outfit mt-1">{card.value}</p>
              </div>
              <Icon className="w-6 h-6 opacity-80 shrink-0" />
            </div>
          );
        })}
      </div>

      {error && (
        <div className="glass-card p-4 rounded-xl border border-rose-500/25 bg-rose-500/10 text-rose-200 text-sm">
          {error}
        </div>
      )}

      {/* Card grid */}
      {loading ? (
        <div className="glass-card p-10 rounded-2xl border border-white/5 text-center text-slate-500 font-mono text-xs">
          Loading sites...
        </div>
      ) : sites.length === 0 ? (
        <div className="glass-card p-10 rounded-2xl border border-white/5 border-dashed text-center text-slate-500 text-sm">
          No sites are being monitored yet. Click <span className="text-cyan-400 font-semibold">Add site</span> to register your first URL.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {sites.map((site) => {
            const downtime = downtimeLabel(site, now);
            const borderTone =
              site.last_status === 'DOWN'
                ? 'border-rose-500/30'
                : site.last_status === 'UP'
                ? 'border-white/5'
                : 'border-white/5';
            return (
              <div
                key={site.id}
                className={`glass-card rounded-2xl border ${borderTone} p-5 flex flex-col gap-3 hover:bg-white/[0.005] transition-colors`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="font-outfit font-bold text-slate-100 truncate">{site.name}</h3>
                    <a
                      href={site.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 text-[11px] font-mono text-cyan-400 hover:text-cyan-300 truncate"
                      title={site.url}
                    >
                      <span className="truncate">{site.url}</span>
                      <ExternalLink className="w-3 h-3 shrink-0" />
                    </a>
                  </div>
                  <StatusPill status={site.last_status} />
                </div>

                <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-400">
                  <div className="flex items-center gap-1.5">
                    <Clock className="w-3 h-3 text-slate-500" />
                    <span>checked {relativeTime(site.last_checked_at, now)}</span>
                  </div>
                  <div className="font-mono text-slate-400 text-right">
                    {site.last_response_ms != null ? `${site.last_response_ms} ms` : '—'}
                  </div>
                  <div className="font-mono text-slate-500">every {site.check_interval_seconds}s</div>
                  <div className="font-mono text-slate-500 text-right">timeout {site.timeout_seconds}s</div>
                </div>

                {downtime && (
                  <div className="px-3 py-1.5 rounded-md bg-rose-500/10 border border-rose-500/20 text-[11px] font-semibold text-rose-300">
                    {downtime}
                  </div>
                )}

                {site.last_error && site.last_status === 'DOWN' && (
                  <div className="px-3 py-2 rounded-md bg-rose-500/5 border border-rose-500/10 font-mono text-[10px] text-rose-300/80 break-words">
                    {site.last_error}
                  </div>
                )}

                <div className="flex gap-2 pt-1">
                  <button
                    onClick={() => handleCheck(site)}
                    disabled={checkingId === site.id}
                    className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 bg-white/2 border border-white/5 text-slate-300 hover:bg-white/5 hover:text-white rounded-md text-xs font-semibold disabled:opacity-50 transition-colors cursor-pointer"
                    title="Check now"
                  >
                    <RefreshCcw className={`w-3.5 h-3.5 ${checkingId === site.id ? 'animate-spin' : ''}`} />
                    Check now
                  </button>
                  <button
                    onClick={() => openEdit(site)}
                    className="px-3 py-1.5 bg-white/2 border border-white/5 text-slate-400 hover:text-cyan-300 hover:bg-white/5 rounded-md transition-colors cursor-pointer"
                    title="Edit settings"
                  >
                    <Settings className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => handleDelete(site)}
                    className="px-3 py-1.5 bg-white/2 border border-white/5 text-slate-500 hover:text-rose-300 hover:bg-rose-500/10 rounded-md transition-colors cursor-pointer"
                    title="Delete"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Add / Edit modal */}
      {mode !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4">
          <div className="w-full max-w-lg glass-card rounded-2xl p-6 border border-white/10 relative">
            <button
              type="button"
              onClick={closeModal}
              className="absolute top-4 right-4 text-slate-400 hover:text-white transition-colors cursor-pointer"
            >
              <X className="w-5 h-5" />
            </button>
            <h3 className="font-outfit font-extrabold text-lg text-slate-100 mb-6 flex items-center gap-2">
              <Globe className="w-5 h-5 text-cyan-400" />
              {mode === 'edit' ? 'Edit site' : 'Add site to monitor'}
            </h3>
            {formError && (
              <div className="mb-4 p-3 rounded-lg bg-rose-500/15 border border-rose-500/20 text-rose-300 text-xs">
                {formError}
              </div>
            )}
            <form onSubmit={handleSubmit} className="space-y-4 text-xs font-semibold">
              <div>
                <label className="block text-slate-400 uppercase tracking-wider mb-2">Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Production API"
                  className="w-full py-2.5 px-3 glass-input text-xs"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-slate-400 uppercase tracking-wider mb-2">URL</label>
                <input
                  type="url"
                  required
                  placeholder="https://api.example.com/health"
                  className="w-full py-2.5 px-3 glass-input text-xs"
                  value={form.url}
                  onChange={(e) => setForm({ ...form, url: e.target.value })}
                />
              </div>

              {/* Advanced collapsible */}
              <button
                type="button"
                onClick={() => setShowAdvanced((v) => !v)}
                className="w-full flex items-center justify-between px-2 py-2 rounded-md text-slate-400 hover:text-slate-200 hover:bg-white/3 transition-colors cursor-pointer text-[11px] uppercase tracking-wider"
              >
                <span>Advanced</span>
                <ChevronDown className={`w-4 h-4 transition-transform ${showAdvanced ? 'rotate-180' : ''}`} />
              </button>

              {showAdvanced && (
                <div className="space-y-4 pl-2 border-l border-white/5">
                  <div>
                    <label className="block text-slate-400 uppercase tracking-wider mb-2">
                      Additional OK codes
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. 401, 403 (treated as UP on top of the default 200-399)"
                      className="w-full py-2.5 px-3 glass-input text-xs font-mono"
                      value={form.additional_ok_codes}
                      onChange={(e) => setForm({ ...form, additional_ok_codes: e.target.value })}
                    />
                    <p className="text-[10px] text-slate-500 mt-1 font-normal leading-relaxed">
                      Useful for authenticated APIs that return 401 to unauthenticated probes —
                      the server is alive, just rejecting the request.
                    </p>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-slate-400 uppercase tracking-wider mb-2">
                        Check every (seconds)
                      </label>
                      <input
                        type="number"
                        min={10}
                        className="w-full py-2.5 px-3 glass-input text-xs font-mono"
                        value={form.check_interval_seconds}
                        onChange={(e) => setForm({ ...form, check_interval_seconds: e.target.value })}
                      />
                    </div>
                    <div>
                      <label className="block text-slate-400 uppercase tracking-wider mb-2">
                        Timeout (seconds)
                      </label>
                      <input
                        type="number"
                        min={1}
                        className="w-full py-2.5 px-3 glass-input text-xs font-mono"
                        value={form.timeout_seconds}
                        onChange={(e) => setForm({ ...form, timeout_seconds: e.target.value })}
                      />
                    </div>
                  </div>
                  {mode === 'edit' && (
                    <label className="flex items-center gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={form.enabled}
                        onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                        className="w-4 h-4 accent-cyan-500"
                      />
                      <span className="text-slate-300 normal-case">
                        Enabled (uncheck to pause monitoring without deleting)
                      </span>
                    </label>
                  )}
                </div>
              )}

              <div className="flex justify-end gap-3 pt-4 border-t border-white/5 font-medium">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-4 py-2 bg-white/2 hover:bg-white/5 border border-white/5 rounded-lg text-slate-400 hover:text-white transition-colors cursor-pointer text-xs"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-2 bg-gradient-to-r from-cyan-500 to-emerald-500 hover:from-cyan-400 hover:to-emerald-400 text-slate-900 font-semibold rounded-lg transition-colors cursor-pointer text-xs disabled:opacity-50"
                >
                  {submitting
                    ? mode === 'edit' ? 'Saving…' : 'Adding…'
                    : mode === 'edit' ? 'Save changes' : 'Add site'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
