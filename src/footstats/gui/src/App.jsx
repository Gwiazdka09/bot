import React, { useState, useEffect } from 'react';
import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area 
} from 'recharts';
import { 
  Wallet, TrendingUp, Calendar, CheckCircle2, XCircle, Clock, Info, ChevronRight, LayoutDashboard, History, Settings, Menu
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const API_BASE = "http://localhost:8000/api";

const App = () => {
  const [status, setStatus] = useState(null);
  const [coupons, setCoupons] = useState([]);
  const [history, setHistory] = useState([]);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState('dashboard'); // 'dashboard', 'history', 'settings'
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statusRes, couponsRes, historyRes, configRes] = await Promise.all([
          fetch(`${API_BASE}/status`),
          fetch(`${API_BASE}/coupons`),
          fetch(`${API_BASE}/bankroll/history`),
          fetch(`${API_BASE}/config`)
        ]);

        const statusData = await statusRes.json();
        const couponsData = await couponsRes.json();
        const historyData = await historyRes.json();
        const configData = await configRes.json();

        setStatus(statusData);
        setCoupons(couponsData);
        setHistory(historyData);
        setConfig(configData);
      } catch (error) {
        console.error("Błąd podczas pobierania danych:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) return (
    <div className="flex items-center justify-center h-screen bg-[#020617] text-white">
      <div className="text-2xl font-bold animate-pulse">Ładowanie Twojego Imperium...</div>
    </div>
  );

  return (
    <div className="flex min-h-screen bg-[#0f172a] text-slate-100 overflow-x-hidden">
      
      {/* Sidebar - Full Height */}
      <aside className={`sidebar hidden lg:flex flex-col fixed top-0 left-0 overflow-y-auto border-r border-white/5 bg-[#0b1120] ${sidebarCollapsed ? 'collapsed w-20' : 'w-64'}`} style={{height: '100%', minHeight: '100vh'}}>
        <div className="flex justify-between items-center mb-12">
          {!sidebarCollapsed && (
            <div className="brand text-3xl font-bold bg-gradient-to-r from-indigo-400 to-pink-400 bg-clip-text text-transparent">
              FootStats
            </div>
          )}
          <button onClick={() => setSidebarCollapsed(!sidebarCollapsed)} className="p-2 hover:bg-white/5 rounded-lg text-slate-400">
            <Menu size={20} />
          </button>
        </div>
        
        <nav className="space-y-4 mb-12">
          <NavItem 
            icon={<LayoutDashboard size={20} />} 
            label="Dashboard" 
            active={view === 'dashboard'} 
            collapsed={sidebarCollapsed}
            onClick={() => setView('dashboard')}
          />
          <NavItem 
            icon={<History size={20} />} 
            label="Historia" 
            active={view === 'history'} 
            collapsed={sidebarCollapsed}
            onClick={() => setView('history')}
          />
          <NavItem 
            icon={<Settings size={20} />} 
            label="Ustawienia" 
            active={view === 'settings'} 
            collapsed={sidebarCollapsed}
            onClick={() => setView('settings')}
          />
        </nav>

        
        {/* Simple User Info at bottom */}
        {!sidebarCollapsed && (
          <div className="mt-auto p-4 bg-white/5 rounded-xl border border-white/5">
            <p className="text-xs text-slate-500 uppercase tracking-tighter">Właściciel</p>
            <p className="font-bold text-slate-300">Jakub</p>
          </div>
        )}
      </aside>

      {/* Main Content Area */}
      <main className={`flex-1 main-content p-6 lg:p-10 ${sidebarCollapsed ? 'lg:ml-20' : 'lg:ml-64'}`}>
        <div className="container">
          <AnimatePresence mode="wait">
            {view === 'dashboard' && (
              <DashboardHome 
                key="dash"
                status={status} 
                history={history} 
                coupons={coupons.slice(0, 4)} 
                onSeeAll={() => setView('history')}
              />
            )}
            {view === 'history' && (
              <HistoryView 
                key="hist"
                coupons={coupons} 
              />
            )}
            {view === 'settings' && (
              <SettingsView 
                key="sett"
                config={config} 
              />
            )}
          </AnimatePresence>
        </div>
      </main>
    </div>
  );
};

// --- Sub Views ---

const DashboardHome = ({ status, history, coupons, onSeeAll }) => (
  <motion.div
    initial={{ opacity: 0, x: 20 }}
    animate={{ opacity: 1, x: 0 }}
    exit={{ opacity: 0, x: -20 }}
  >
    <header className="mb-10 flex justify-between items-start">
      <div>
        <h1 className="text-4xl font-bold mb-2">Witaj, Jakub</h1>
        <p className="text-slate-400">Twoje imperium bukmacherskie jest online.</p>
      </div>
      {status && (
        <div className="glass-card p-4 border-indigo-500/20 bg-indigo-500/5 shrink-0">
          <div className="flex items-center gap-2 mb-1">
            <Wallet size={14} className="text-indigo-400" />
            <p className="text-xs text-slate-400 uppercase tracking-wider font-semibold">Dostępny Balans</p>
          </div>
          <p className="text-2xl font-bold text-white text-right">{status.bankroll?.toFixed(2)} <span className="text-sm font-normal text-slate-400">PLN</span></p>
        </div>
      )}
    </header>

    <section className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
      <StatCard 
        title="Skuteczność" 
        value={`${status?.stats?.roi_pct > 0 ? '+' : ''}${status?.stats?.roi_pct}%`} 
        subtitle="Zwrot z Inwestycji (ROI)"
        icon={<TrendingUp className="text-emerald-400" />}
        color="emerald"
        delay={0.1}
      />
      <StatCard 
        title="Wygrane Kupony" 
        value={status?.stats?.wins || 0} 
        subtitle={`Z ostatnich ${status?.stats?.total_finished} kuponów`}
        icon={<CheckCircle2 className="text-indigo-400" />}
        color="indigo"
        delay={0.2}
      />
      <StatCard 
        title="Następna Analiza" 
        value="16:00" 
        subtitle="Dynamiczne sprawdzanie składów"
        icon={<Clock className="text-pink-400" />}
        color="pink"
        delay={0.3}
      />
    </section>

    <section className="glass-card p-8 mb-8">
      <h2 className="text-xl font-bold mb-8 flex items-center gap-2">
        <TrendingUp size={22} className="text-indigo-400" /> Progresja Bankrolla
      </h2>
      <div className="h-[350px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={history}>
            <defs>
              <linearGradient id="colorBal" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#818cf8" stopOpacity={0.4}/>
                <stop offset="95%" stopColor="#818cf8" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
            <XAxis dataKey="time" hide />
            <YAxis hide domain={['auto', 'auto']} />
            <Tooltip 
              contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: '12px', color: '#fff', boxShadow: '0 10px 15px -3px rgba(0,0,0,0.5)' }}
            />
            <Area type="monotone" dataKey="balance" stroke="#818cf8" strokeWidth={4} fillOpacity={1} fill="url(#colorBal)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>

    <section>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold">Najnowsze Predykcje</h2>
        <button onClick={onSeeAll} className="btn-see-all">
          Zobacz historię <ChevronRight size={16} />
        </button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {coupons.length > 0 ? coupons.map((c, i) => (
          <CouponCard key={c.id} coupon={c} index={i} />
        )) : (
          <div className="md:col-span-2 text-center p-12 glass-card text-slate-500">Brak aktywnych kuponów w bazie.</div>
        )}
      </div>
    </section>
  </motion.div>
);

const HistoryView = ({ coupons }) => (
  <motion.div 
    initial={{ opacity: 0, scale: 0.98 }}
    animate={{ opacity: 1, scale: 1 }}
    exit={{ opacity: 0, scale: 0.98 }}
  >
    <div className="mb-12">
      <h1 className="text-4xl font-bold mb-2">Pełna Historia</h1>
      <p className="text-slate-400">Podgląd wszystkich kuponów zapisanych w bazie danych.</p>
    </div>
    <div className="grid grid-cols-1 gap-4">
      {coupons.length > 0 ? coupons.map((c, i) => {
        const statusColor = c.status === 'WON' ? 'emerald' : c.status === 'LOST' ? 'rose' : 'amber';
        const statusIcon = c.status === 'WON' ? <CheckCircle2 size={20} /> : c.status === 'LOST' ? <XCircle size={20} /> : <Clock size={20} />;
        return (
          <div key={c.id} className="glass-card overflow-hidden">
            {/* Row header */}
            <div className="px-6 py-4 flex items-center justify-between border-b border-white/5 bg-white/[0.02]">
              <div className="flex items-center gap-3">
                <div className={`w-9 h-9 rounded-full flex items-center justify-center bg-${statusColor}-500/10 text-${statusColor}-400`}>
                  {statusIcon}
                </div>
                <div>
                  <p className="font-bold text-sm">Kupon #{c.id}</p>
                  <p className="text-xs text-slate-500">{c.phase?.toUpperCase()} · {c.created_at?.slice(0, 10)}</p>
                </div>
              </div>
              <span className={`text-xs font-bold px-3 py-1 rounded-full bg-${statusColor}-500/10 text-${statusColor}-400`}>
                {c.status}
              </span>
            </div>
            {/* Stats row */}
            <div className="px-6 py-4 flex items-center gap-10">
              <div>
                <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Kurs łączny</p>
                <p className="text-lg font-bold text-indigo-300">{c.total_odds?.toFixed(2)}</p>
              </div>
              <div className="w-px h-8 bg-white/5" />
              <div>
                <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Stawka</p>
                <p className="text-lg font-bold text-white">{c.stake_pln} <span className="text-xs text-slate-400 font-normal">PLN</span></p>
              </div>
              <div className="w-px h-8 bg-white/5" />
              <div>
                <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Wypłata</p>
                <p className={`text-lg font-bold ${c.payout_pln ? 'text-emerald-400' : 'text-slate-600'}`}>
                  {c.payout_pln ? `${c.payout_pln} PLN` : '—'}
                </p>
              </div>
            </div>
          </div>
        );
      }) : (
        <div className="text-center p-24 glass-card text-slate-500">Historia jest pusta. Postaw pierwszy kupon!</div>
      )}
    </div>
  </motion.div>
);

const SettingsView = ({ config }) => (
  <motion.div
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    exit={{ opacity: 0, y: -20 }}
  >
    <div className="mb-10">
      <h1 className="text-4xl font-bold mb-2">Ustawienia Bota</h1>
      <p className="text-slate-400">Parametry analityczne i finansowe silnika FootStats.</p>
    </div>

    {/* Status systemu */}
    <div className="glass-card p-6 mb-6 flex items-center gap-4 border-emerald-500/20 bg-emerald-500/5">
      <div className="w-3 h-3 rounded-full bg-emerald-500 shadow-[0_0_12px_rgba(16,185,129,0.6)] animate-pulse" />
      <div>
        <p className="font-bold text-sm text-emerald-400">System aktywny</p>
        <p className="text-xs text-slate-500">Bot działa poprawnie · Wersja {config?.version || 'N/A'}</p>
      </div>
    </div>

    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
      {/* Algorytm */}
      <div className="glass-card p-6">
        <div className="flex items-center gap-2 mb-6">
          <div className="p-2 bg-indigo-500/10 rounded-lg"><TrendingUp size={16} className="text-indigo-400" /></div>
          <h3 className="font-bold">Algorytm & Ryzyko</h3>
        </div>
        <div className="space-y-1">
          <ConfigItem label="Próg Pewniaczka" value={`${config?.pewniaczek_prog || 0}%`} />
          <ConfigItem label="Próg Kandydatów" value={`${config?.min_confidence ? (config.min_confidence * 100).toFixed(0) : 0}%`} />
          <ConfigItem label="Fractional Kelly" value={`f* / ${config?.kelly_fraction || 0}`} />
          <ConfigItem label="Min. kurs" value={config?.min_odds || '—'} />
          <ConfigItem label="Max. kurs" value={config?.max_odds || '—'} />
        </div>
      </div>

      {/* Finanse */}
      <div className="glass-card p-6">
        <div className="flex items-center gap-2 mb-6">
          <div className="p-2 bg-pink-500/10 rounded-lg"><Wallet size={16} className="text-pink-400" /></div>
          <h3 className="font-bold">Bankroll & Stawki</h3>
        </div>
        <div className="space-y-1">
          <ConfigItem label="Min. stawka" value={`${config?.min_stake_pln || 5} PLN`} />
          <ConfigItem label="Max. stawka" value={`${config?.max_stake_pln || 20} PLN`} />
          <ConfigItem label="Model AI" value={config?.groq_model || 'llama3-70b'} />
          <ConfigItem label="Tryb" value={config?.dry_run ? 'DRY-RUN' : 'PRODUKCJA'} badge={config?.dry_run ? 'amber' : 'emerald'} />
        </div>
      </div>
    </div>

    {/* Info footer */}
    <div className="glass-card p-5 flex items-start gap-4 bg-white/[0.01] border-white/5">
      <Info size={16} className="text-slate-500 mt-0.5 shrink-0" />
      <p className="text-xs text-slate-500 leading-relaxed">
        Parametry odczytywane z <code className="text-slate-400 bg-white/5 px-1 rounded">config.py</code>.
        Edycja przez panel zostanie udostępniona w kolejnej wersji systemu.
      </p>
    </div>
  </motion.div>
);

// --- Helpers ---

const NavItem = ({ icon, label, active, collapsed, onClick }) => (
  <div 
    onClick={onClick}
    className={`nav-item flex items-center gap-4 px-4 py-3 rounded-xl cursor-pointer transition-all ${active ? 'bg-indigo-500/15 text-indigo-400 border border-indigo-500/25' : 'text-slate-400 hover:bg-white/5 hover:text-white'}`}
  >
    <div className={active ? 'text-indigo-400' : 'text-slate-500'}>{icon}</div>
    {!collapsed && <span className="nav-label font-semibold">{label}</span>}
  </div>
);

const StatCard = ({ title, value, subtitle, icon, color, delay }) => (
  <motion.div 
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ delay }}
    className="glass-card p-8"
  >
    <div className="flex justify-between items-start mb-6">
      <div className={`p-3 bg-${color}-500/10 rounded-xl`}>{icon}</div>
    </div>
    <h3 className="text-slate-500 text-sm font-semibold uppercase tracking-wider mb-2">{title}</h3>
    <div className="text-4xl font-bold mb-2 tracking-tight">{value}</div>
    <p className="text-slate-400 text-xs">{subtitle}</p>
  </motion.div>
);

const CouponCard = ({ coupon, index }) => (
  <motion.div 
    initial={{ opacity: 0, scale: 0.95 }}
    animate={{ opacity: 1, scale: 1 }}
    transition={{ delay: index * 0.1 }}
    className="glass-card overflow-hidden group hover:border-indigo-500/30 transition-all"
  >
    <div className="p-6 border-b border-white/5 flex justify-between items-center bg-white/5">
      <div className="flex items-center gap-3">
        <div className={`w-3 h-3 rounded-full ${coupon.status === 'WON' ? 'bg-emerald-500 shadow-[0_0_15px_rgba(16,185,129,0.5)]' : coupon.status === 'LOST' ? 'bg-rose-500' : 'bg-amber-500 animate-pulse outline outline-4 outline-amber-500/10'}`}></div>
        <span className="font-bold tracking-tight">Kupon #{coupon.id} <span className="text-xs text-slate-500 ml-2 font-normal">[{coupon.phase.toUpperCase()}]</span></span>
      </div>
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Calendar size={12} /> {coupon.created_at.slice(0, 10)}
      </div>
    </div>
    <div className="p-6 space-y-5">
      {coupon.legs.map((leg, i) => (
        <div key={i} className="flex justify-between items-start">
          <div className="flex-1">
            <p className="text-sm font-bold text-slate-200">{leg.home} - {leg.away}</p>
            <p className="text-xs text-slate-500 flex items-center gap-1 mt-1"><Info size={10} /> Typ: <span className="text-slate-300">{leg.tip}</span></p>
          </div>
          <div className="text-sm font-bold bg-indigo-500/10 text-indigo-300 px-3 py-1 rounded-lg">@{leg.odds}</div>
        </div>
      ))}
    </div>
    <div className="px-6 py-5 bg-white/[0.04] flex justify-between items-center mt-auto border-t border-white/5">
      <div className="flex gap-8">
        <div>
          <p className="text-[10px] text-slate-500 uppercase tracking-widest font-bold mb-1">Kurs</p>
          <p className="text-xl font-bold text-white tracking-tighter">{coupon.total_odds.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-[10px] text-slate-500 uppercase tracking-widest font-bold mb-1">Stawka</p>
          <p className="text-xl font-bold text-indigo-400 tracking-tighter">{coupon.stake_pln} <span className="text-xs">PLN</span></p>
        </div>
      </div>
      <div className="text-right">
        <div className={`text-xs font-bold px-3 py-1 rounded-full ${coupon.status === 'WON' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-white/5 text-slate-500'}`}>
          {coupon.status === 'WON' ? 'ZWROT: ' + coupon.payout_pln + ' PLN' : coupon.status}
        </div>
      </div>
    </div>
  </motion.div>
);

const ConfigItem = ({ label, value, badge }) => (
  <div className="flex justify-between items-center py-3 border-b border-white/5 last:border-0">
    <span className="text-sm text-slate-400">{label}</span>
    {badge ? (
      <span className={`text-xs font-bold px-2 py-0.5 rounded-full bg-${badge}-500/10 text-${badge}-400`}>{value}</span>
    ) : (
      <span className="text-sm font-bold text-slate-200">{value}</span>
    )}
  </div>
);

export default App;
