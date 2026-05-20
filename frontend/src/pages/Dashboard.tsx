import { useEffect, useMemo, useState } from 'react';
import { 
  Activity, 
  CheckCircle2, 
  XCircle, 
  AlertOctagon, 
  Terminal
} from 'lucide-react';
import { 
  AreaChart, 
  Area, 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer 
} from 'recharts';
import { api } from '../services/api';

interface IncidentSummary {
  id: number;
  incident_uid: string;
  severity: string;
  system: string;
  status: string;
  root_cause: string;
  timestamp: string;
}

interface TrendPoint {
  name: string;
  success: number;
  failure: number;
}

interface CategoryPoint {
  category: string;
  count: number;
}

const severityColors: Record<string, string> = {
  Critical: 'bg-rose-500/10 text-rose-400 border-rose-500/20 text-glow-rose',
  High: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  Medium: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  Low: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
};

const statusColors: Record<string, string> = {
  Open: 'bg-rose-500/10 text-rose-400 border-rose-500/15 animate-pulse',
  Investigating: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/15',
  Resolved: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/15',
  Closed: 'bg-slate-500/10 text-slate-400 border-slate-500/15',
};

export default function Dashboard() {
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchDashboardData() {
      try {
        const res = await api.get('/incidents/');
        setIncidents(res.data);
      } catch (err) {
        console.error('Failed to fetch dashboard incidents:', err);
      } finally {
        setLoading(false);
      }
    }
    fetchDashboardData();
  }, []);

  const stats = useMemo(() => {
    const failedCount = incidents.length;
    const activeIncidents = incidents.filter((incident) => incident.status !== 'Resolved' && incident.status !== 'Closed').length;
    const resolvedCount = incidents.filter((incident) => incident.status === 'Resolved' || incident.status === 'Closed').length;
    const totalTracked = failedCount + resolvedCount;

    return {
      totalDeployments: totalTracked,
      successCount: resolvedCount,
      failedCount,
      activeIncidents,
      analysesCompleted: incidents.length
    };
  }, [incidents]);

  const trendData = useMemo<TrendPoint[]>(() => {
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const buckets = new Map<string, TrendPoint>();

    incidents.forEach((incident) => {
      const name = days[new Date(incident.timestamp).getDay()];
      const current = buckets.get(name) || { name, success: 0, failure: 0 };
      if (incident.status === 'Resolved' || incident.status === 'Closed') {
        current.success += 1;
      } else {
        current.failure += 1;
      }
      buckets.set(name, current);
    });

    return Array.from(buckets.values());
  }, [incidents]);

  const categoryData = useMemo<CategoryPoint[]>(() => {
    const counts = new Map<string, number>();
    incidents.forEach((incident) => {
      counts.set(incident.system, (counts.get(incident.system) || 0) + 1);
    });

    return Array.from(counts, ([category, count]) => ({ category, count }));
  }, [incidents]);

  const statCards = [
    { name: 'Tracked Incidents', value: stats.totalDeployments, icon: Activity, color: 'text-indigo-400', bg: 'bg-indigo-500/10 border-indigo-500/15' },
    { name: 'Resolved Ratio', value: stats.totalDeployments > 0 ? `${((stats.successCount / stats.totalDeployments) * 100).toFixed(0)}%` : '0%', icon: CheckCircle2, color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/15' },
    { name: 'Incident Count', value: stats.failedCount, icon: XCircle, color: 'text-rose-400', bg: 'bg-rose-500/10 border-rose-500/15' },
    { name: 'Active Incidents', value: stats.activeIncidents, icon: AlertOctagon, color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/15' },
  ];

  return (
    <div className="space-y-8">
      {/* Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {statCards.map((card, idx) => {
          const Icon = card.icon;
          return (
            <div key={idx} className={`glass-card p-6 rounded-2xl border flex items-center justify-between ${card.bg}`}>
              <div>
                <p className="text-slate-400 text-xs font-semibold uppercase tracking-wider">{card.name}</p>
                <p className={`text-3xl font-extrabold font-outfit mt-2 ${card.color}`}>{card.value}</p>
              </div>
              <div className={`w-12 h-12 rounded-xl flex items-center justify-center bg-white/3 border border-white/5`}>
                <Icon className={`w-6 h-6 ${card.color}`} />
              </div>
            </div>
          );
        })}
      </div>

      {/* Analytics Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Trend Area Chart */}
        <div className="glass-card p-6 rounded-2xl border border-white/5">
          <div className="mb-6 flex justify-between items-center">
            <h3 className="font-outfit font-bold text-slate-200">Weekly Incident History</h3>
            <span className="text-[10px] text-cyan-400 font-mono tracking-widest bg-cyan-400/10 border border-cyan-500/15 px-2 py-0.5 rounded">
              RESOLVED VS ACTIVE
            </span>
          </div>
          <div className="h-80 w-full">
            {trendData.length === 0 ? (
              <div className="h-full flex items-center justify-center text-xs text-slate-500 font-mono">
                No incident trend data yet.
              </div>
            ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={trendData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorSuccess" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.2}/>
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="colorFailure" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.2}/>
                    <stop offset="95%" stopColor="#f43f5e" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.03)" />
                <XAxis dataKey="name" stroke="#64748b" fontSize={11} tickLine={false} />
                <YAxis stroke="#64748b" fontSize={11} tickLine={false} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#0d1121', borderColor: 'rgba(255,255,255,0.08)', borderRadius: 8, color: '#e2e8f0' }}
                  labelStyle={{ fontWeight: 'bold', color: '#a5b4fc' }}
                />
                <Area type="monotone" dataKey="success" stroke="#10b981" strokeWidth={2} fillOpacity={1} fill="url(#colorSuccess)" />
                <Area type="monotone" dataKey="failure" stroke="#f43f5e" strokeWidth={2} fillOpacity={1} fill="url(#colorFailure)" />
              </AreaChart>
            </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* RCA Categories Bar Chart */}
        <div className="glass-card p-6 rounded-2xl border border-white/5">
          <div className="mb-6 flex justify-between items-center">
            <h3 className="font-outfit font-bold text-slate-200">Root Cause Distribution</h3>
            <span className="text-[10px] text-indigo-400 font-mono tracking-widest bg-indigo-400/10 border border-indigo-500/15 px-2 py-0.5 rounded">
              PLATFORM FAULTS
            </span>
          </div>
          <div className="h-80 w-full">
            {categoryData.length === 0 ? (
              <div className="h-full flex items-center justify-center text-xs text-slate-500 font-mono">
                No root cause categories yet.
              </div>
            ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={categoryData} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.03)" />
                <XAxis dataKey="category" stroke="#64748b" fontSize={11} tickLine={false} />
                <YAxis stroke="#64748b" fontSize={11} tickLine={false} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#0d1121', borderColor: 'rgba(255,255,255,0.08)', borderRadius: 8, color: '#e2e8f0' }}
                />
                <Bar dataKey="count" fill="#818cf8" radius={[4, 4, 0, 0]} barSize={25} />
              </BarChart>
            </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>

      {/* Incidents Activity Log */}
      <div className="glass-card rounded-2xl border border-white/5 overflow-hidden">
        <div className="p-6 border-b border-white/5 flex justify-between items-center">
          <h3 className="font-outfit font-bold text-slate-200 flex items-center gap-2">
            <Terminal className="w-5 h-5 text-cyan-400" />
            <span>Recent Platform Incidents</span>
          </h3>
          <span className="text-[10px] text-slate-400 font-mono">
            UPDATED: Real-time
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-white/[0.02] text-xs font-semibold text-slate-400 uppercase tracking-wider border-b border-white/5">
              <tr>
                <th className="px-6 py-4">Incident ID</th>
                <th className="px-6 py-4">System</th>
                <th className="px-6 py-4">Severity</th>
                <th className="px-6 py-4">Root Cause</th>
                <th className="px-6 py-4">Status</th>
                <th className="px-6 py-4 text-right">Registered</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-6 py-8 text-center text-slate-500 font-mono">
                    Polling active incidents...
                  </td>
                </tr>
              ) : incidents.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-8 text-center text-slate-500 font-mono">
                    No open incidents logged. Sync Jenkins servers to register analytical faults.
                  </td>
                </tr>
              ) : (
                incidents.map((incident) => {
                  return (
                    <tr key={incident.id} className="hover:bg-white/[0.01] transition-colors">
                      <td className="px-6 py-4 font-mono font-bold text-xs text-indigo-400">
                        {incident.incident_uid}
                      </td>
                      <td className="px-6 py-4 font-semibold text-slate-300">
                        {incident.system}
                      </td>
                      <td className="px-6 py-4">
                        <span className={`px-2 py-0.5 rounded border text-[10px] font-mono uppercase tracking-wider ${severityColors[incident.severity] || severityColors.Medium}`}>
                          {incident.severity}
                        </span>
                      </td>
                      <td className="px-6 py-4 max-w-sm truncate text-slate-400 text-xs">
                        {incident.root_cause}
                      </td>
                      <td className="px-6 py-4">
                        <span className={`px-2 py-0.5 rounded border text-[10px] font-semibold uppercase tracking-wider ${statusColors[incident.status]}`}>
                          {incident.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-right text-xs text-slate-500 font-mono">
                        {new Date(incident.timestamp).toLocaleTimeString()}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
