import React, { useCallback, useEffect, useState } from 'react';
import { 
  Server, 
  Plus, 
  Terminal, 
  RefreshCw, 
  Trash2,
  Settings,
  AlertTriangle, 
  CheckCircle,
  HelpCircle,
  Clock,
  Database
} from 'lucide-react';
import { api } from '../services/api';
import RcaView from '../components/RcaView';

interface JenkinsServer {
  id: number;
  name: string;
  url: string;
}

interface Job {
  id: number;
  name: string;
  url: string;
  last_status: string;
}

interface JenkinsJobCandidate {
  name: string;
  url: string;
  last_status: string | null;
  monitored: boolean;
}

interface Build {
  id: number;
  number: number;
  status: string;
  duration: number;
  timestamp: string;
}

interface RcaData {
  id: number;
  root_cause: string;
  possible_issues: string[];
  recommendations: string[];
  confidence_score: number;
  parsed_errors: {
    line_number: number;
    content: string;
    severity: string;
    category: string;
  }[];
  priority_level: string;
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

export default function JenkinsJobs() {
  const [servers, setServers] = useState<JenkinsServer[]>([]);
  const [selectedServer, setSelectedServer] = useState<JenkinsServer | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [builds, setBuilds] = useState<Build[]>([]);
  const [availableJobs, setAvailableJobs] = useState<JenkinsJobCandidate[]>([]);
  const [selectedPipelineUrls, setSelectedPipelineUrls] = useState<Set<string>>(new Set());
  const [showPipelinePicker, setShowPipelinePicker] = useState(false);
  
  // Connection Modal state
  const [showConnect, setShowConnect] = useState(false);
  const [serverName, setServerName] = useState('');
  const [serverUrl, setServerUrl] = useState('');
  const [username, setUsername] = useState('');
  const [apiToken, setApiToken] = useState('');
  
  // RCA Sheet state
  const [showRca, setShowRca] = useState(false);
  const [rcaData, setRcaData] = useState<RcaData | null>(null);
  const [analyzingBuildId, setAnalyzingBuildId] = useState<number | null>(null);

  const [loading, setLoading] = useState(false);
  const [pipelineLoading, setPipelineLoading] = useState(false);
  const [buildsLoading, setBuildsLoading] = useState(false);
  const [error, setError] = useState('');
  const [pipelineError, setPipelineError] = useState('');
  const [buildError, setBuildError] = useState('');

  // 1. Fetch connected servers
  const fetchServers = useCallback(async () => {
    try {
      const res = await api.get('/jenkins/servers');
      setServers(res.data);
      if (res.data.length > 0 && !selectedServer) {
        setSelectedServer(res.data[0]);
      }
    } catch (err) {
      console.error('Failed to fetch Jenkins servers:', err);
    }
  }, [selectedServer]);

  const openPipelinePicker = useCallback(async (server: JenkinsServer) => {
    setPipelineError('');
    setPipelineLoading(true);
    setShowPipelinePicker(true);
    try {
      const res = await api.get(`/jenkins/servers/${server.id}/available-jobs`);
      const candidates: JenkinsJobCandidate[] = res.data;
      setAvailableJobs(candidates);
      setSelectedPipelineUrls(new Set(
        candidates.filter((job) => job.monitored).map((job) => job.url)
      ));
    } catch (err: unknown) {
      setPipelineError(getApiErrorMessage(err, 'Failed to fetch Jenkins pipelines.'));
    } finally {
      setPipelineLoading(false);
    }
  }, []);

  const syncBuilds = useCallback(async (job: Job) => {
    setBuildError('');
    setBuildsLoading(true);
    try {
      const res = await api.get(`/jenkins/jobs/${job.id}/builds`);
      setBuilds(res.data);
    } catch (err: unknown) {
      console.error('Failed to fetch builds:', err);
      setBuildError(getApiErrorMessage(err, 'Failed to fetch Jenkins builds.'));
    } finally {
      setBuildsLoading(false);
    }
  }, []);

  useEffect(() => {
    let ignore = false;

    async function loadServers() {
      try {
        const res = await api.get('/jenkins/servers');
        if (!ignore) {
          setServers(res.data);
          if (res.data.length > 0 && !selectedServer) {
            setSelectedServer(res.data[0]);
          }
        }
      } catch (err) {
        console.error('Failed to fetch Jenkins servers:', err);
      }
    }

    void loadServers();

    return () => {
      ignore = true;
    };
  }, [selectedServer]);

  // 2. Fetch jobs when selected server changes
  useEffect(() => {
    if (!selectedServer) return;
    let ignore = false;
    const serverId = selectedServer.id;

    async function loadJobs() {
      try {
        const res = await api.get(`/jenkins/jobs?server_id=${serverId}`);
        if (!ignore) {
          setJobs(res.data);
          if (res.data.length > 0) {
            setSelectedJob(res.data[0]);
          } else {
            setSelectedJob(null);
            setBuilds([]);
          }
        }
      } catch (err) {
        console.error('Failed to fetch Jenkins jobs:', err);
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }

    void loadJobs();

    return () => {
      ignore = true;
    };
  }, [selectedServer]);

  // 3. Fetch builds when selected job changes
  useEffect(() => {
    if (!selectedJob) return;
    let ignore = false;
    const job = selectedJob;

    async function loadBuilds() {
      setBuildError('');
      setBuildsLoading(true);
      try {
        const res = await api.get(`/jenkins/jobs/${job.id}/builds`);
        if (!ignore) {
          setBuilds(res.data);
        }
      } catch (err: unknown) {
        console.error('Failed to fetch builds:', err);
        if (!ignore) {
          setBuildError(getApiErrorMessage(err, 'Failed to fetch Jenkins builds.'));
        }
      } finally {
        if (!ignore) {
          setBuildsLoading(false);
        }
      }
    }

    void loadBuilds();

    return () => {
      ignore = true;
    };
  }, [selectedJob]);

  const handleConnectServer = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await api.post('/jenkins/connect', {
        name: serverName,
        url: serverUrl,
        username,
        api_token: apiToken
      });
      setShowConnect(false);
      setServerName('');
      setUsername('');
      setApiToken('');
      
      // Refresh server list and select the new one
      await fetchServers();
      setSelectedServer(res.data);
      await openPipelinePicker(res.data);
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, 'Failed to establish Jenkins link.'));
    } finally {
      setLoading(false);
    }
  };

  const handleSyncJobs = async () => {
    if (selectedServer) {
      openPipelinePicker(selectedServer);
    }
  };

  const handleSaveMonitoredPipelines = async () => {
    if (!selectedServer) return;
    setPipelineError('');
    setPipelineLoading(true);
    try {
      const selectedJobs = availableJobs.filter((job) => selectedPipelineUrls.has(job.url));
      const res = await api.put(`/jenkins/servers/${selectedServer.id}/monitored-jobs`, {
        jobs: selectedJobs,
      });
      setJobs(res.data);
      const nextSelectedJob = res.data[0] || null;
      setSelectedJob(nextSelectedJob);
      if (nextSelectedJob) {
        await syncBuilds(nextSelectedJob);
      } else {
        setBuilds([]);
      }
      setShowPipelinePicker(false);
    } catch (err: unknown) {
      setPipelineError(getApiErrorMessage(err, 'Failed to save monitored pipelines.'));
    } finally {
      setPipelineLoading(false);
    }
  };

  const handleDeleteServer = async (server: JenkinsServer) => {
    const confirmed = window.confirm(`Delete ${server.name} and all stored Jenkins data for it?`);
    if (!confirmed) return;

    try {
      await api.delete(`/jenkins/servers/${server.id}`);
      const remainingServers = servers.filter((srv) => srv.id !== server.id);
      setServers(remainingServers);
      setSelectedServer(remainingServers[0] || null);
      setJobs([]);
      setSelectedJob(null);
      setBuilds([]);
    } catch (err: unknown) {
      alert(getApiErrorMessage(err, 'Failed to delete Jenkins server.'));
    }
  };

  const togglePipeline = (jobUrl: string) => {
    setSelectedPipelineUrls((current) => {
      const next = new Set(current);
      if (next.has(jobUrl)) {
        next.delete(jobUrl);
      } else {
        next.add(jobUrl);
      }
      return next;
    });
  };

  const handleAnalyzeBuild = async (buildId: number) => {
    setAnalyzingBuildId(buildId);
    try {
      const res = await api.post(`/jenkins/builds/${buildId}/analyze`);
      setRcaData(res.data);
      setShowRca(true);
    } catch (err) {
      console.error('Failed to run AI RCA on build:', err);
      alert('AI troubleshooting engine encountered an anomaly.');
    } finally {
      setAnalyzingBuildId(null);
    }
  };

  const handleRefreshBuilds = async () => {
    if (selectedJob) {
      await syncBuilds(selectedJob);
    }
  };

  const formatDuration = (ms: number) => {
    const totalSecs = Math.floor(ms / 1000);
    const mins = Math.floor(totalSecs / 60);
    const secs = totalSecs % 60;
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'SUCCESS':
        return (
          <span className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-emerald-500/20 bg-emerald-500/10 text-emerald-400 text-[10px] font-semibold tracking-wider">
            <CheckCircle className="w-3.5 h-3.5" />
            <span>SUCCESS</span>
          </span>
        );
      case 'FAILURE':
        return (
          <span className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-rose-500/20 bg-rose-500/10 text-rose-400 text-[10px] font-semibold tracking-wider text-glow-rose">
            <AlertTriangle className="w-3.5 h-3.5 animate-pulse" />
            <span>FAILURE</span>
          </span>
        );
      case 'ABORTED':
        return (
          <span className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-slate-500/20 bg-slate-500/10 text-slate-400 text-[10px] font-semibold tracking-wider">
            <HelpCircle className="w-3.5 h-3.5" />
            <span>ABORTED</span>
          </span>
        );
      default:
        return (
          <span className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-cyan-500/20 bg-cyan-500/10 text-cyan-400 text-[10px] font-semibold tracking-wider pulse-glow">
            <Clock className="w-3.5 h-3.5" />
            <span>RUNNING</span>
          </span>
        );
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
      {/* Sidebar Control Panel (Servers and Jobs) */}
      <div className="lg:col-span-4 space-y-6">
        {/* Servers Card */}
        <div className="glass-card p-6 rounded-2xl border border-white/5">
          <div className="flex justify-between items-center mb-4">
            <h3 className="font-outfit font-bold text-slate-200 flex items-center gap-2">
              <Server className="w-4.5 h-4.5 text-cyan-400" />
              <span>Jenkins Domain</span>
            </h3>
            <button 
              onClick={() => setShowConnect(true)}
              className="p-1 rounded bg-indigo-500/15 border border-indigo-500/20 text-indigo-300 hover:text-white hover:bg-indigo-500/35 transition-colors cursor-pointer"
              title="Connect server"
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>

          {servers.length === 0 ? (
            <div className="p-4 text-center rounded-xl bg-white/2 border border-dashed border-white/5 text-slate-500 text-xs">
              No Jenkins servers linked. Click + to initialize.
            </div>
          ) : (
            <div className="space-y-2">
              {servers.map((srv) => (
                <div
                  key={srv.id}
                  className={`w-full p-3.5 rounded-xl border text-xs font-semibold flex items-center justify-between gap-2 transition-all ${
                    selectedServer?.id === srv.id
                      ? 'bg-indigo-600/15 border-indigo-500/30 text-slate-200 shadow-sm'
                      : 'bg-white/2 border-white/5 text-slate-400 hover:text-slate-300 hover:bg-white/3'
                  }`}
                >
                  <button
                    onClick={() => setSelectedServer(srv)}
                    className="min-w-0 flex-1 text-left cursor-pointer"
                  >
                    <p className="font-bold truncate">{srv.name}</p>
                    <p className="text-[10px] text-slate-500 font-mono truncate mt-1">{srv.url}</p>
                  </button>
                  <button
                    onClick={() => openPipelinePicker(srv)}
                    className="p-1 rounded text-slate-500 hover:text-cyan-300 hover:bg-white/5 cursor-pointer"
                    title="Select pipelines"
                  >
                    <Settings className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handleDeleteServer(srv)}
                    className="p-1 rounded text-slate-500 hover:text-rose-300 hover:bg-rose-500/10 cursor-pointer"
                    title="Delete Jenkins server"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Jobs Card */}
        <div className="glass-card p-6 rounded-2xl border border-white/5">
          <div className="flex justify-between items-center mb-4">
            <h3 className="font-outfit font-bold text-slate-200 flex items-center gap-2">
              <Terminal className="w-4.5 h-4.5 text-cyan-400" />
              <span>Monitored Pipelines</span>
            </h3>
            <button 
              onClick={handleSyncJobs}
              disabled={pipelineLoading || !selectedServer}
              className="p-1 rounded bg-white/3 border border-white/5 text-slate-400 hover:text-slate-200 hover:bg-white/5 disabled:opacity-50 transition-colors cursor-pointer"
            >
              <RefreshCw className={`w-4 h-4 ${pipelineLoading ? 'animate-spin' : ''}`} />
            </button>
          </div>

          {jobs.length === 0 ? (
            <div className="p-4 text-center rounded-xl bg-white/2 border border-dashed border-white/5 text-slate-500 text-xs">
              Select pipelines to monitor from a linked Jenkins server.
            </div>
          ) : (
            <div className="space-y-1.5 max-h-[400px] overflow-y-auto pr-1">
              {jobs.map((job) => {
                const isSelected = selectedJob?.id === job.id;
                return (
                  <button
                    key={job.id}
                    onClick={() => setSelectedJob(job)}
                    className={`w-full text-left px-3 py-2.5 rounded-lg border text-xs flex items-center justify-between transition-all cursor-pointer ${
                      isSelected
                        ? 'bg-gradient-to-r from-indigo-500/10 to-transparent border-indigo-500/25 text-indigo-200 text-glow-indigo font-bold'
                        : 'bg-white/[0.01] border-white/5 text-slate-400 hover:bg-white/2 hover:text-slate-300'
                    }`}
                  >
                    <span className="truncate pr-2">{job.name}</span>
                    <span className={`w-2 h-2 rounded-full shrink-0 ${job.last_status === 'SUCCESS' ? 'bg-emerald-400' : 'bg-rose-500'}`}></span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Main Panel (Builds list) */}
      <div className="lg:col-span-8">
        <div className="glass-card rounded-2xl border border-white/5 overflow-hidden">
          <div className="p-6 border-b border-white/5 flex justify-between items-center">
            <div>
              <h3 className="font-outfit font-bold text-slate-200 flex items-center gap-2">
                <Database className="w-5 h-5 text-indigo-400" />
                <span>Build Execution History</span>
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                Pipeline: <span className="font-mono text-cyan-400">{selectedJob?.name || 'none'}</span>
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handleRefreshBuilds}
                disabled={!selectedJob || buildsLoading}
                className="p-1.5 rounded bg-white/3 border border-white/5 text-slate-400 hover:text-slate-200 hover:bg-white/5 disabled:opacity-50 transition-colors cursor-pointer"
                title="Sync latest builds"
              >
                <RefreshCw className={`w-4 h-4 ${buildsLoading ? 'animate-spin' : ''}`} />
              </button>
              <span className="text-[10px] text-slate-400 font-mono bg-white/3 border border-white/5 px-2.5 py-1 rounded">
                TOTAL BUILDS: {builds.length}
              </span>
            </div>
          </div>

          <div className="divide-y divide-white/5">
            {buildError && (
              <div className="p-4 bg-rose-500/10 border-b border-rose-500/20 text-rose-300 text-xs">
                {buildError}
              </div>
            )}
            {buildsLoading && builds.length === 0 ? (
              <div className="p-8 text-center text-slate-500 font-mono text-xs">
                Synchronizing pipeline telemetry...
              </div>
            ) : builds.length === 0 ? (
              <div className="p-8 text-center text-slate-500 font-mono text-xs">
                Select an active job to observe build logs and sync statistics.
              </div>
            ) : (
              builds.map((build) => {
                const isAnalyzing = analyzingBuildId === build.id;
                return (
                  <div key={build.id} className="p-6 flex items-center justify-between hover:bg-white/[0.005] transition-colors">
                    <div className="flex items-center gap-8">
                      <span className="font-mono font-bold text-slate-400 w-16">
                        #{build.number}
                      </span>
                      <div className="w-28">
                        {getStatusBadge(build.status)}
                      </div>
                      <div className="flex items-center gap-2 text-slate-400 text-xs">
                        <Clock className="w-4 h-4 text-slate-500" />
                        <span>{formatDuration(build.duration)}</span>
                      </div>
                      <span className="text-xs text-slate-500 font-mono">
                        {new Date(build.timestamp).toLocaleDateString()}
                      </span>
                    </div>

                    <div>
                      {build.status === 'FAILURE' ? (
                        <button
                          onClick={() => handleAnalyzeBuild(build.id)}
                          disabled={isAnalyzing}
                          className="px-4 py-2 bg-gradient-to-r from-rose-500/10 to-rose-600/20 hover:from-rose-500/20 hover:to-rose-600/30 text-rose-300 border border-rose-500/30 rounded-lg text-xs font-semibold flex items-center gap-2 transition-all glow-btn cursor-pointer disabled:opacity-50"
                        >
                          <Terminal className="w-4 h-4 shrink-0" />
                          <span>{isAnalyzing ? 'Analyzing Failure...' : 'Sync & Analyze'}</span>
                        </button>
                      ) : (
                        <button
                          disabled
                          className="px-4 py-2 bg-white/2 text-slate-600 border border-white/5 rounded-lg text-xs font-semibold flex items-center gap-2 cursor-not-allowed"
                        >
                          <CheckCircle className="w-4 h-4" />
                          <span>Healthy</span>
                        </button>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* Connect Server Modal Overlay */}
      {showConnect && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4">
          <div className="w-full max-w-lg glass-card rounded-2xl p-6 border border-white/10 relative">
            <button 
              onClick={() => setShowConnect(false)}
              className="absolute top-4 right-4 text-slate-400 hover:text-white transition-colors cursor-pointer"
            >
              <X className="w-5 h-5" />
            </button>
            <h3 className="font-outfit font-extrabold text-lg text-slate-100 mb-6 flex items-center gap-2">
              <Server className="w-5 h-5 text-cyan-400" />
              <span>Link Jenkins Endpoint</span>
            </h3>

            {error && (
              <div className="mb-4 p-3 rounded-lg bg-rose-500/15 border border-rose-500/20 text-rose-300 text-xs">
                {error}
              </div>
            )}

            <form onSubmit={handleConnectServer} className="space-y-4 text-xs font-semibold">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-slate-400 uppercase tracking-wider mb-2">Endpoint Name</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Corp Jenkins"
                    className="w-full py-2.5 px-3 glass-input text-xs"
                    value={serverName}
                    onChange={(e) => setServerName(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-slate-400 uppercase tracking-wider mb-2">Jenkins URL</label>
                  <input
                    type="url"
                    required
                    className="w-full py-2.5 px-3 glass-input text-xs"
                    value={serverUrl}
                    onChange={(e) => setServerUrl(e.target.value)}
                  />
                </div>
              </div>

              <div>
                <label className="block text-slate-400 uppercase tracking-wider mb-2">Username (Optional)</label>
                <input
                  type="text"
                  placeholder="admin"
                  className="w-full py-2.5 px-3 glass-input text-xs"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>

              <div>
                <label className="block text-slate-400 uppercase tracking-wider mb-2">API Token / Password (Optional)</label>
                <input
                  type="password"
                  placeholder="••••••••"
                  className="w-full py-2.5 px-3 glass-input text-xs"
                  value={apiToken}
                  onChange={(e) => setApiToken(e.target.value)}
                />
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-white/5 font-medium">
                <button
                  type="button"
                  onClick={() => setShowConnect(false)}
                  className="px-4 py-2 bg-white/2 hover:bg-white/5 border border-white/5 rounded-lg text-slate-400 hover:text-white transition-colors cursor-pointer text-xs"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="px-4 py-2 bg-gradient-to-r from-indigo-600 to-cyan-500 hover:from-indigo-500 hover:to-cyan-400 text-white rounded-lg transition-colors cursor-pointer glow-btn text-xs disabled:opacity-50"
                >
                  {loading ? 'Testing link...' : 'Save & Link'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showPipelinePicker && selectedServer && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4">
          <div className="w-full max-w-2xl glass-card rounded-2xl p-6 border border-white/10 relative">
            <button
              onClick={() => setShowPipelinePicker(false)}
              className="absolute top-4 right-4 text-slate-400 hover:text-white transition-colors cursor-pointer"
            >
              <X className="w-5 h-5" />
            </button>
            <h3 className="font-outfit font-extrabold text-lg text-slate-100 mb-1 flex items-center gap-2">
              <Terminal className="w-5 h-5 text-cyan-400" />
              <span>Select Pipelines</span>
            </h3>
            <p className="text-xs text-slate-500 font-mono mb-5 truncate">{selectedServer.url}</p>

            {pipelineError && (
              <div className="mb-4 p-3 rounded-lg bg-rose-500/15 border border-rose-500/20 text-rose-300 text-xs">
                {pipelineError}
              </div>
            )}

            <div className="rounded-xl border border-white/5 overflow-hidden max-h-96 overflow-y-auto">
              {pipelineLoading ? (
                <div className="p-8 text-center text-slate-500 font-mono text-xs">
                  Fetching Jenkins pipelines...
                </div>
              ) : availableJobs.length === 0 ? (
                <div className="p-8 text-center text-slate-500 font-mono text-xs">
                  No pipelines returned by Jenkins.
                </div>
              ) : (
                availableJobs.map((job) => {
                  const checked = selectedPipelineUrls.has(job.url);
                  return (
                    <label
                      key={job.url}
                      className="flex items-center gap-4 p-4 border-b border-white/5 last:border-b-0 hover:bg-white/[0.02] cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => togglePipeline(job.url)}
                        className="w-4 h-4 accent-cyan-500"
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-semibold text-slate-200 truncate">{job.name}</p>
                        <p className="text-[10px] text-slate-500 font-mono truncate mt-1">{job.url}</p>
                      </div>
                      <span className={`w-2 h-2 rounded-full shrink-0 ${job.last_status === 'SUCCESS' ? 'bg-emerald-400' : job.last_status === 'FAILURE' ? 'bg-rose-500' : 'bg-cyan-400'}`}></span>
                    </label>
                  );
                })
              )}
            </div>

            <div className="flex justify-between items-center gap-3 pt-4 mt-4 border-t border-white/5">
              <span className="text-xs text-slate-500 font-mono">
                SELECTED: {selectedPipelineUrls.size}
              </span>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => setShowPipelinePicker(false)}
                  className="px-4 py-2 bg-white/2 hover:bg-white/5 border border-white/5 rounded-lg text-slate-400 hover:text-white transition-colors cursor-pointer text-xs"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSaveMonitoredPipelines}
                  disabled={pipelineLoading}
                  className="px-4 py-2 bg-gradient-to-r from-indigo-600 to-cyan-500 hover:from-indigo-500 hover:to-cyan-400 text-white rounded-lg transition-colors cursor-pointer glow-btn text-xs disabled:opacity-50"
                >
                  Save Monitoring
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* AI RCA sheet panel */}
      <RcaView 
        data={rcaData} 
        isOpen={showRca} 
        onClose={() => setShowRca(false)} 
      />
    </div>
  );
}

// Simple absolute icons for Connect Modal Close since Lucide X was missing
function X(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M18 6 6 18" />
      <path d="m6 6 12 12" />
    </svg>
  );
}
