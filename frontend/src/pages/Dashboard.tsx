import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertOctagon,
  ChevronDown,
  Cpu,
  Eraser,
  Eye,
  FileSearch,
  GitBranch,
  Hammer,
  Lightbulb,
  ListChecks,
  RefreshCcw,
  ShieldCheck,
  Wrench,
} from 'lucide-react';
import { api } from '../services/api';

// Match the backend poll interval so the activity feed stays in sync without
// the user clicking refresh.
const AUTO_REFRESH_MS = 10_000;

type SafetyClass = 'READ_ONLY' | 'SAFE_ACTION' | 'BLOCKED';

interface AgentAction {
  id: number;
  build_id: number;
  build_number: number | null;
  job_name: string | null;
  action_type: string;
  status: string;
  tool_name: string | null;
  reason: string | null;
  developer_email: string | null;
  created_at: string;
}

interface Tool {
  name: string;
  safety: SafetyClass;
  description: string;
}

interface AgentPoll {
  id: number;
  job_id: number;
  job_name: string | null;
  build_number: number | null;
  status: string | null;
  error: string | null;
  created_at: string;
}

interface BuildBucket {
  build_id: number;
  build_number: number | null;
  job_name: string | null;
  actions: AgentAction[];
  latest_created_at: string;
}

// The six stages of the agent loop, in order. (REPORT was removed — see the
// activity feed itself if you want the agent's summary.)
const STAGE_ORDER: string[] = [
  'OBSERVE',
  'UNDERSTAND_CONTEXT',
  'PLAN',
  'CHOOSE',
  'EXECUTE',
  'VERIFY',
];

const STAGE_META: Record<
  string,
  { label: string; icon: React.ComponentType<{ className?: string }>; tone: string }
> = {
  OBSERVE: { label: 'Observe', icon: Eye, tone: 'text-slate-300 border-slate-500/25 bg-slate-500/10' },
  UNDERSTAND_CONTEXT: { label: 'Context', icon: FileSearch, tone: 'text-cyan-300 border-cyan-500/25 bg-cyan-500/10' },
  PLAN: { label: 'Plan', icon: Lightbulb, tone: 'text-indigo-300 border-indigo-500/25 bg-indigo-500/10' },
  CHOOSE: { label: 'Choose', icon: ListChecks, tone: 'text-violet-300 border-violet-500/25 bg-violet-500/10' },
  EXECUTE: { label: 'Execute', icon: Hammer, tone: 'text-amber-300 border-amber-500/25 bg-amber-500/10' },
  VERIFY: { label: 'Verify', icon: ShieldCheck, tone: 'text-emerald-300 border-emerald-500/25 bg-emerald-500/10' },
};

const SAFETY_META: Record<SafetyClass, { label: string; tone: string }> = {
  READ_ONLY: { label: 'read-only', tone: 'text-cyan-300 border-cyan-500/25 bg-cyan-500/10' },
  SAFE_ACTION: { label: 'safe action', tone: 'text-emerald-300 border-emerald-500/25 bg-emerald-500/10' },
  BLOCKED: { label: 'blocked', tone: 'text-rose-300 border-rose-500/25 bg-rose-500/10' },
};

function statusTone(status: string): string {
  const s = status.toLowerCase();
  if (['triggered', 'verified', 'sent', 'completed', 'selected', 'observed'].includes(s)) {
    return 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20';
  }
  if (['retry'].includes(s)) {
    return 'text-amber-300 bg-amber-500/10 border-amber-500/20';
  }
  if (['notify_only', 'observe_only', 'skipped', 'notool', 'loggedonly'].includes(s)) {
    return 'text-slate-300 bg-slate-500/10 border-slate-500/20';
  }
  if (['blocked', 'failed', 'unknowntool', 'unsupported'].includes(s)) {
    return 'text-rose-300 bg-rose-500/10 border-rose-500/20';
  }
  return 'text-indigo-300 bg-indigo-500/10 border-indigo-500/20';
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

export default function Dashboard() {
  const [actions, setActions] = useState<AgentAction[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [polls, setPolls] = useState<AgentPoll[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [showTools, setShowTools] = useState(false);
  const [showFetchLog, setShowFetchLog] = useState(true);
  // Wall-clock of the most recent successful refresh, used to render the
  // "last fetched Ns ago" counter below the live spinner.
  const [lastFetchedAt, setLastFetchedAt] = useState<number | null>(null);
  const [nowTick, setNowTick] = useState<number>(Date.now());
  // Stable refresh closure for the auto-interval below.
  const refreshRef = useRef<((showSpinner?: boolean) => Promise<void>) | undefined>(undefined);

  const refresh = async (showSpinner = false) => {
    if (showSpinner) setRefreshing(true);
    setError(null);
    try {
      const [actionsRes, toolsRes, pollsRes] = await Promise.all([
        api.get<AgentAction[]>('/agent/actions?limit=200'),
        api.get<Tool[]>('/agent/tools'),
        api.get<AgentPoll[]>('/agent/polls?limit=200'),
      ]);
      setActions(actionsRes.data);
      setTools(toolsRes.data);
      setPolls(pollsRes.data);
      setLastFetchedAt(Date.now());
    } catch (err) {
      console.error('Failed to load agent activity:', err);
      setError('Failed to load agent activity feed.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };
  refreshRef.current = refresh;

  useEffect(() => {
    void refresh();
    // Mirror the backend poll cadence so new agent activity appears without
    // the user clicking refresh.
    const id = window.setInterval(() => {
      void refreshRef.current?.(false);
    }, AUTO_REFRESH_MS);
    // Once-a-second clock for the "Ns ago" label.
    const clock = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => {
      window.clearInterval(id);
      window.clearInterval(clock);
    };
  }, []);

  const lastFetchedAgo = useMemo(() => {
    if (lastFetchedAt == null) return null;
    const secs = Math.max(0, Math.round((nowTick - lastFetchedAt) / 1000));
    return secs;
  }, [lastFetchedAt, nowTick]);

  const buildBuckets: BuildBucket[] = useMemo(() => {
    const buckets = new Map<number, BuildBucket>();
    for (const a of actions) {
      let bucket = buckets.get(a.build_id);
      if (!bucket) {
        bucket = {
          build_id: a.build_id,
          build_number: a.build_number,
          job_name: a.job_name,
          actions: [],
          latest_created_at: a.created_at,
        };
        buckets.set(a.build_id, bucket);
      }
      bucket.actions.push(a);
      if (a.created_at > bucket.latest_created_at) {
        bucket.latest_created_at = a.created_at;
      }
      // Capture build/job labels lazily — earliest non-null wins.
      if (bucket.build_number == null && a.build_number != null) bucket.build_number = a.build_number;
      if (!bucket.job_name && a.job_name) bucket.job_name = a.job_name;
    }
    for (const b of buckets.values()) {
      b.actions.sort((x, y) => x.created_at.localeCompare(y.created_at));
    }
    return Array.from(buckets.values()).sort((a, b) =>
      b.latest_created_at.localeCompare(a.latest_created_at),
    );
  }, [actions]);

  const stats = useMemo(() => {
    const retries = actions.filter(
      (a) =>
        a.action_type === 'EXECUTE' &&
        a.tool_name === 'jenkins.retry_build' &&
        a.status === 'Triggered',
    ).length;
    const wipes = actions.filter(
      (a) =>
        a.action_type === 'EXECUTE' &&
        a.tool_name === 'jenkins.clean_workspace' &&
        a.status === 'Wiped',
    ).length;
    const blocked = actions.filter((a) => a.status === 'Blocked').length;
    return {
      builds: buildBuckets.length,
      retries,
      wipes,
      blocked,
    };
  }, [actions, buildBuckets]);

  const toggleExpanded = (buildId: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(buildId)) next.delete(buildId);
      else next.add(buildId);
      return next;
    });
  };

  const statCards = [
    { name: 'Builds Handled', value: stats.builds, icon: GitBranch, tone: 'text-indigo-300 bg-indigo-500/10 border-indigo-500/20' },
    { name: 'Retries Triggered', value: stats.retries, icon: RefreshCcw, tone: 'text-amber-300 bg-amber-500/10 border-amber-500/20' },
    { name: 'Workspaces Wiped', value: stats.wipes, icon: Eraser, tone: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20' },
    { name: 'Blocked Attempts', value: stats.blocked, icon: AlertOctagon, tone: 'text-rose-300 bg-rose-500/10 border-rose-500/20' },
  ];

  return (
    <div className="space-y-8">
      {/* Header card */}
      <div className="glass-card p-6 rounded-2xl border border-white/5 flex items-center gap-6">
        <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/20 shrink-0">
          <Cpu className="w-7 h-7 text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="font-outfit font-extrabold text-xl text-slate-100">DevOps Copilot Agent</h2>
          <p className="text-sm text-slate-400 mt-1">
            Polls every 10s. Acts on FAILUREs through Observe → Understand → Plan → Choose → Execute → Verify.
          </p>
          {/* Live-poll indicator — circular spinner + last-fetched timer. Makes the */}
          {/* "alive but nothing to report" state visually unambiguous. */}
          <div className="mt-3 flex items-center gap-2 text-[11px] font-mono text-cyan-300">
            <span
              className="inline-block w-3 h-3 rounded-full border-2 border-cyan-400/30 border-t-cyan-400 animate-spin"
              title="Polling every 10s"
            />
            <span className="text-slate-400">
              polling every 10s
              {lastFetchedAgo != null && (
                <>
                  {' · '}
                  <span className="text-cyan-300">last fetched {lastFetchedAgo}s ago</span>
                </>
              )}
            </span>
          </div>
        </div>
        <button
          onClick={() => refresh(true)}
          disabled={refreshing}
          className="p-2 rounded-lg bg-white/3 border border-white/5 text-slate-300 hover:text-white hover:bg-white/5 disabled:opacity-50 transition-colors cursor-pointer"
          title="Refresh activity feed"
        >
          <RefreshCcw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {statCards.map((card) => {
          const Icon = card.icon;
          return (
            <div
              key={card.name}
              className={`glass-card p-4 rounded-2xl border flex items-center justify-between ${card.tone}`}
            >
              <div className="min-w-0">
                <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider truncate">
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

      {/* Activity feed */}
      <div className="glass-card rounded-2xl border border-white/5 overflow-hidden">
        <div className="p-6 border-b border-white/5 flex justify-between items-center">
          <h3 className="font-outfit font-bold text-slate-200 flex items-center gap-2">
            <Activity className="w-5 h-5 text-cyan-400" />
            <span>Agent Activity</span>
          </h3>
          <span className="text-[10px] text-slate-400 font-mono uppercase tracking-widest">
            Most recent first
          </span>
        </div>

        {loading ? (
          <div className="p-10 text-center text-slate-500 font-mono text-xs">
            Loading agent ledger...
          </div>
        ) : buildBuckets.length === 0 ? (
          <div className="p-10 text-center text-slate-500 text-sm">
            No agent activity yet. Link a Jenkins server under{' '}
            <span className="text-cyan-400 font-mono">Jenkins Sync</span> and let a failed build
            trigger the loop, or call <span className="text-cyan-400 font-mono">POST /agent/run-once</span>.
          </div>
        ) : (
          <ul className="divide-y divide-white/5">
            {buildBuckets.map((bucket) => {
              const isOpen = expanded.has(bucket.build_id);
              const planRow = bucket.actions.find((a) => a.action_type === 'PLAN');
              const executeRow = bucket.actions.find((a) => a.action_type === 'EXECUTE');
              const stagesPresent = new Set(bucket.actions.map((a) => a.action_type));

              return (
                <li key={bucket.build_id} className="px-6 py-5 hover:bg-white/[0.005] transition-colors">
                  <button
                    type="button"
                    onClick={() => toggleExpanded(bucket.build_id)}
                    className="w-full flex flex-col md:flex-row md:items-center md:justify-between gap-3 text-left cursor-pointer"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <ChevronDown
                        className={`w-4 h-4 text-slate-500 transition-transform shrink-0 ${
                          isOpen ? 'rotate-180' : ''
                        }`}
                      />
                      <span className="font-mono text-sm font-bold text-cyan-300 truncate">
                        {bucket.job_name ?? `build_id=${bucket.build_id}`}
                      </span>
                      {bucket.build_number != null && (
                        <span className="font-mono font-bold text-slate-400 text-sm">
                          #{bucket.build_number}
                        </span>
                      )}
                      {planRow && (
                        <span
                          className={`px-2 py-0.5 rounded border text-[10px] font-semibold uppercase tracking-wider ${statusTone(
                            planRow.status,
                          )}`}
                        >
                          plan: {planRow.status}
                        </span>
                      )}
                      {executeRow?.tool_name && (
                        <span className="px-2 py-0.5 rounded border border-white/10 bg-white/5 text-[10px] font-mono text-slate-300">
                          {executeRow.tool_name}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {STAGE_ORDER.map((stage) => {
                        const meta = STAGE_META[stage];
                        const Icon = meta.icon;
                        const present = stagesPresent.has(stage);
                        return (
                          <span
                            key={stage}
                            title={meta.label + (present ? ' — recorded' : ' — not recorded')}
                            className={`w-6 h-6 rounded-md border flex items-center justify-center ${
                              present ? meta.tone : 'text-slate-600 border-white/5 bg-white/[0.02]'
                            }`}
                          >
                            <Icon className="w-3 h-3" />
                          </span>
                        );
                      })}
                      <span className="ml-2 text-[10px] text-slate-500 font-mono">
                        {formatTime(bucket.latest_created_at)}
                      </span>
                    </div>
                  </button>

                  {isOpen && (
                    <ol className="mt-4 space-y-2 pl-7 border-l border-white/5">
                      {bucket.actions.map((a) => {
                        const meta = STAGE_META[a.action_type] ?? {
                          label: a.action_type,
                          icon: Activity,
                          tone: 'text-slate-300 border-slate-500/25 bg-slate-500/10',
                        };
                        const Icon = meta.icon;
                        return (
                          <li key={a.id} className="flex items-start gap-3">
                            <span
                              className={`mt-0.5 w-6 h-6 rounded-md border flex items-center justify-center shrink-0 ${meta.tone}`}
                            >
                              <Icon className="w-3 h-3" />
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2 text-xs">
                                <span className="font-semibold text-slate-200">{meta.label}</span>
                                <span
                                  className={`px-2 py-0.5 rounded border text-[10px] font-semibold uppercase tracking-wider ${statusTone(
                                    a.status,
                                  )}`}
                                >
                                  {a.status}
                                </span>
                                {a.tool_name && (
                                  <span className="px-2 py-0.5 rounded border border-white/10 bg-white/5 text-[10px] font-mono text-slate-300">
                                    {a.tool_name}
                                  </span>
                                )}
                                {a.developer_email && (
                                  <span className="text-[10px] text-slate-500 font-mono truncate">
                                    → {a.developer_email}
                                  </span>
                                )}
                                <span className="ml-auto text-[10px] text-slate-500 font-mono">
                                  {formatTime(a.created_at)}
                                </span>
                              </div>
                              {a.reason && (
                                <p className="mt-1 text-xs text-slate-400 leading-relaxed whitespace-pre-wrap">
                                  {a.reason}
                                </p>
                              )}
                            </div>
                          </li>
                        );
                      })}
                    </ol>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Agent Fetch Log — every poll-tick fetch, even when nothing happened.
          Proves the loop is alive and shows what it saw on each monitored job. */}
      <div className="glass-card rounded-2xl border border-white/5 overflow-hidden">
        <button
          type="button"
          onClick={() => setShowFetchLog((v) => !v)}
          className="w-full p-6 border-b border-white/5 flex items-center justify-between cursor-pointer hover:bg-white/[0.01]"
        >
          <h3 className="font-outfit font-bold text-slate-200 flex items-center gap-2">
            <FileSearch className="w-5 h-5 text-cyan-400" />
            <span>Agent Fetch Log</span>
            <span className="ml-2 text-[10px] text-slate-400 font-mono">
              monitoring {polls.length} {polls.length === 1 ? 'job' : 'jobs'}
            </span>
          </h3>
          <ChevronDown className={`w-4 h-4 text-slate-500 transition-transform ${showFetchLog ? 'rotate-180' : ''}`} />
        </button>
        {showFetchLog && (
          polls.length === 0 ? (
            <div className="p-10 text-center text-slate-500 text-sm">
              No jobs polled yet. Either the backend hasn't restarted since the agent was enabled,
              or no jobs are being monitored. Add one under <span className="text-cyan-400 font-mono">Jenkins Sync</span>.
            </div>
          ) : (
            <ul className="divide-y divide-white/5 max-h-96 overflow-y-auto">
              {polls.map((p) => {
                const isError = p.error != null;
                const statusPill = isError
                  ? 'text-rose-300 bg-rose-500/10 border-rose-500/20'
                  : p.status === 'FAILURE'
                  ? 'text-rose-300 bg-rose-500/10 border-rose-500/20'
                  : p.status === 'SUCCESS'
                  ? 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20'
                  : p.status === 'ABORTED'
                  ? 'text-slate-300 bg-slate-500/10 border-slate-500/20'
                  : p.status === 'RUNNING'
                  ? 'text-cyan-300 bg-cyan-500/10 border-cyan-500/20'
                  : 'text-slate-400 bg-slate-500/5 border-slate-500/10';
                return (
                  <li key={p.id} className="px-6 py-2.5 flex items-center gap-3 text-xs">
                    <span className="font-mono text-cyan-300 truncate flex-1 min-w-0" title={p.job_name ?? ''}>
                      {p.job_name ?? `job_id=${p.job_id}`}
                    </span>
                    <span className="font-mono text-slate-400 w-20 text-right">
                      {p.build_number != null ? `#${p.build_number}` : '—'}
                    </span>
                    <span className={`px-2 py-0.5 rounded border text-[10px] font-semibold uppercase tracking-wider w-24 text-center ${statusPill}`}>
                      {isError ? 'error' : p.status ?? 'none'}
                    </span>
                    <span className="font-mono text-slate-500 w-40 text-right">
                      {formatTime(p.created_at)}
                    </span>
                    {p.error && (
                      <span className="font-mono text-rose-400 truncate flex-1 min-w-0" title={p.error}>
                        {p.error}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )
        )}
      </div>

      {/* Tools catalog */}
      <div className="glass-card rounded-2xl border border-white/5 overflow-hidden">
        <button
          type="button"
          onClick={() => setShowTools((v) => !v)}
          className="w-full p-6 border-b border-white/5 flex items-center justify-between cursor-pointer hover:bg-white/[0.01]"
        >
          <h3 className="font-outfit font-bold text-slate-200 flex items-center gap-2">
            <Wrench className="w-5 h-5 text-indigo-400" />
            <span>Tool Catalog</span>
            <span className="ml-2 text-[10px] text-slate-400 font-mono">{tools.length} tools</span>
          </h3>
          <ChevronDown className={`w-4 h-4 text-slate-500 transition-transform ${showTools ? 'rotate-180' : ''}`} />
        </button>
        {showTools && (
          <ul className="divide-y divide-white/5">
            {tools.map((tool) => {
              const safety = SAFETY_META[tool.safety];
              return (
                <li key={tool.name} className="px-6 py-3 flex items-start gap-3">
                  <span
                    className={`px-2 py-0.5 rounded border text-[10px] font-semibold uppercase tracking-wider shrink-0 ${safety.tone}`}
                  >
                    {safety.label}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-xs font-bold text-slate-200">{tool.name}</p>
                    <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">{tool.description}</p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
