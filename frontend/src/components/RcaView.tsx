import React from 'react';
import { 
  X, 
  Cpu, 
  HelpCircle, 
  Activity, 
  AlertOctagon, 
  ClipboardCopy, 
  Check,
  Terminal
} from 'lucide-react';

interface ParsedError {
  line_number: number;
  content: string;
  severity: string;
  category: string;
}

interface RcaData {
  id: number;
  root_cause: string;
  possible_issues: string[];
  recommendations: string[];
  confidence_score: number;
  parsed_errors: ParsedError[];
  priority_level: string;
}

interface RcaViewProps {
  data: RcaData | null;
  isOpen: boolean;
  onClose: () => void;
}

export default function RcaView({ data, isOpen, onClose }: RcaViewProps) {
  const [copiedIndex, setCopiedIndex] = React.useState<number | null>(null);

  if (!isOpen || !data) return null;

  const copyToClipboard = (text: string, index: number) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const getPriorityColor = (level: string) => {
    switch (level) {
      case 'Critical': return 'text-rose-400 border-rose-500/25 bg-rose-500/10 text-glow-rose';
      case 'High': return 'text-orange-400 border-orange-500/25 bg-orange-500/10';
      case 'Medium': return 'text-amber-400 border-amber-500/25 bg-amber-500/10';
      default: return 'text-slate-400 border-slate-500/25 bg-slate-500/10';
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-end bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-2xl h-screen glass-card border-l border-white/10 flex flex-col p-8 overflow-y-auto animate-slide-in">
        
        {/* Sheet Header */}
        <div className="flex justify-between items-center pb-6 border-b border-white/5 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <Cpu className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="font-extrabold font-outfit text-lg tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-white to-slate-200">
                AI ROOT CAUSE ANALYSIS
              </h2>
              <p className="text-[10px] text-cyan-400 font-mono tracking-wider uppercase">
                Diagnostic Session #{data.id}
              </p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="w-8 h-8 rounded-lg bg-white/3 border border-white/5 flex items-center justify-center text-slate-400 hover:text-slate-200 hover:bg-white/5 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Diagnostic Metadata */}
        <div className="grid grid-cols-2 gap-4 my-6">
          <div className="p-4 rounded-xl bg-white/2 border border-white/5">
            <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider block">Priority Classification</span>
            <span className={`inline-block mt-2 px-3 py-1 rounded-full border text-xs font-semibold ${getPriorityColor(data.priority_level)}`}>
              {data.priority_level}
            </span>
          </div>

          <div className="p-4 rounded-xl bg-white/2 border border-white/5">
            <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider block">Confidence Rating</span>
            <div className="flex items-center gap-3 mt-2">
              <span className="text-xl font-bold font-outfit text-cyan-400">{data.confidence_score}%</span>
              <div className="flex-1 h-2 bg-slate-800 rounded-full overflow-hidden">
                <div 
                  className="h-full bg-gradient-to-r from-indigo-500 to-cyan-400 rounded-full shadow-[0_0_10px_rgba(6,182,212,0.5)]" 
                  style={{ width: `${data.confidence_score}%` }}
                ></div>
              </div>
            </div>
          </div>
        </div>

        {/* Core Analysis block */}
        <div className="space-y-6 flex-1">
          {/* Root Cause explanation */}
          <div className="p-5 rounded-2xl bg-indigo-500/[0.04] border border-indigo-500/10">
            <h4 className="text-xs font-bold text-indigo-400 uppercase tracking-widest flex items-center gap-2 mb-3">
              <AlertOctagon className="w-4 h-4" />
              <span>Identified Root Cause</span>
            </h4>
            <p className="text-sm text-slate-300 leading-relaxed">
              {data.root_cause}
            </p>
          </div>

          {/* Actionable Recommendations */}
          <div>
            <h4 className="text-xs font-bold text-cyan-400 uppercase tracking-widest flex items-center gap-2 mb-4">
              <Activity className="w-4 h-4" />
              <span>Recommended Remediations</span>
            </h4>
            <div className="space-y-3">
              {data.recommendations.map((rec, idx) => (
                <div key={idx} className="p-4 rounded-xl bg-slate-900/60 border border-white/5 flex items-start gap-4 hover:border-cyan-500/10 transition-colors">
                  <span className="w-6 h-6 rounded-lg bg-cyan-500/10 border border-cyan-500/15 flex items-center justify-center text-xs font-bold text-cyan-400 shrink-0 font-mono">
                    {idx + 1}
                  </span>
                  <p className="text-xs text-slate-300 flex-1 leading-relaxed">{rec}</p>
                  <button 
                    onClick={() => copyToClipboard(rec, idx)}
                    className="p-1.5 rounded-md hover:bg-white/5 text-slate-500 hover:text-slate-300 transition-colors cursor-pointer shrink-0"
                    title="Copy command"
                  >
                    {copiedIndex === idx ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <ClipboardCopy className="w-3.5 h-3.5" />}
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Alternative Diagnoses */}
          {data.possible_issues && data.possible_issues.length > 0 && (
            <div>
              <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest flex items-center gap-2 mb-3">
                <HelpCircle className="w-4 h-4" />
                <span>Alternate Diagnostic Contexts</span>
              </h4>
              <ul className="list-disc pl-5 text-xs text-slate-400 space-y-2">
                {data.possible_issues.map((issue, idx) => (
                  <li key={idx} className="leading-relaxed">{issue}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Parsed System Log Extracts */}
          {data.parsed_errors && data.parsed_errors.length > 0 && (
            <div>
              <h4 className="text-xs font-bold text-rose-400 uppercase tracking-widest flex items-center gap-2 mb-3">
                <Terminal className="w-4 h-4" />
                <span>Extracted Error Log Signatures</span>
              </h4>
              <div className="rounded-xl border border-white/5 overflow-hidden">
                <div className="bg-white/[0.01] p-3 border-b border-white/5 text-[10px] text-slate-500 font-mono flex justify-between">
                  <span>LOG LINE AND SIGNATURE</span>
                  <span>CATEGORY</span>
                </div>
                <div className="divide-y divide-white/5 font-mono max-h-60 overflow-y-auto">
                  {data.parsed_errors.map((err, idx) => (
                    <div key={idx} className="p-3 bg-[#0d1121]/80 flex justify-between items-start gap-4 hover:bg-slate-900/60 transition-colors text-[11px]">
                      <div className="flex gap-3">
                        <span className="text-slate-500 select-none">L{err.line_number}</span>
                        <span className="text-rose-300 break-all">{err.content}</span>
                      </div>
                      <span className="px-2 py-0.5 rounded bg-rose-500/10 border border-rose-500/15 text-[9px] text-rose-400 uppercase shrink-0 font-semibold tracking-wider">
                        {err.category}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
