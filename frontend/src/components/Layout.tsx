import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  Terminal,
  LogOut,
  User,
  Cpu,
  Activity,
} from "lucide-react";
import { useAuthStore } from "../store/auth_store";

export default function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const logout = useAuthStore((state) => state.logout);
  const user = useAuthStore((state) => state.user);

  const menuItems = [
    { name: "Dashboard", path: "/dashboard", icon: LayoutDashboard },
    { name: "Jenkins Sync", path: "/jenkins", icon: Terminal },
  ];

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen flex text-slate-100 bg-[#070913]">
      {/* Premium Sidebar */}
      <aside className="w-64 glass-card border-r border-white/5 flex flex-col shrink-0">
        {/* Brand Header */}
        <div className="p-6 border-b border-white/5 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <Cpu className="w-5 h-5 text-white" />
          </div>
          <div>
            <h2 className="font-extrabold font-outfit text-sm tracking-wide bg-clip-text text-transparent bg-gradient-to-r from-white to-cyan-300">
              DevOps COPILOT
            </h2>
            <span className="text-[10px] text-cyan-400 font-mono tracking-widest uppercase">
              AGENT V1.0.0
            </span>
          </div>
        </div>

        {/* User profile capsule */}
        {user && (
          <div className="mx-4 my-6 p-4 rounded-xl bg-white/3 border border-white/5 flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-slate-800 flex items-center justify-center border border-white/10 shrink-0">
              <User className="w-4.5 h-4.5 text-cyan-400" />
            </div>
            <div className="overflow-hidden">
              <p className="text-xs font-semibold truncate">{user.username}</p>
              <p className="text-[10px] text-slate-400 truncate capitalize">
                {user.role}
              </p>
            </div>
          </div>
        )}

        {/* Navigation list */}
        <nav className="flex-1 px-3 space-y-1.5">
          {menuItems.map((item) => {
            const isActive = location.pathname === item.path;
            const Icon = item.icon;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all duration-200 group ${
                  isActive
                    ? "bg-gradient-to-r from-indigo-600/35 to-cyan-500/10 border-l-3 border-cyan-400 text-cyan-200 text-glow-cyan shadow-sm shadow-cyan-400/5"
                    : "text-slate-400 hover:text-slate-200 hover:bg-white/3"
                }`}
              >
                <Icon
                  className={`w-4.5 h-4.5 transition-transform duration-200 ${isActive ? "text-cyan-400" : "text-slate-400 group-hover:scale-105"}`}
                />
                <span>{item.name}</span>
              </Link>
            );
          })}
        </nav>

        {/* Footer actions */}
        <div className="p-4 border-t border-white/5 space-y-3">
          <div className="flex items-center gap-2 text-[10px] font-mono text-emerald-400 bg-emerald-500/10 border border-emerald-500/15 py-1.5 px-3 rounded-md pulse-glow">
            <Activity className="w-3.5 h-3.5" />
            <span>AI ENGINE ONLINE</span>
          </div>

          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-3 px-4 py-3 rounded-lg text-sm text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 transition-colors duration-200 cursor-pointer"
          >
            <LogOut className="w-4.5 h-4.5" />
            <span>Sign Out</span>
          </button>
        </div>
      </aside>

      {/* Main content body */}
      <main className="flex-1 flex flex-col min-w-0 overflow-y-auto">
        <header className="h-16 border-b border-white/5 flex items-center justify-between px-8 bg-white/[0.01] shrink-0">
          <h1 className="font-outfit font-bold text-lg text-slate-200 capitalize">
            {location.pathname.substring(1) || "Dashboard"} Overview
          </h1>
          <div className="text-[11px] font-mono text-slate-400 bg-white/3 px-3 py-1 rounded border border-white/5">
            NODE_ENV: <span className="text-cyan-400">development</span>
          </div>
        </header>

        <div className="flex-1 p-8 overflow-y-auto">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
