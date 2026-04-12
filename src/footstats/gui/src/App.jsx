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
      <aside className={`sidebar hidden lg:flex flex-col glass-card p-6 fixed h-screen border-y-0 border-l-0 rounded-none ${sidebarCollapsed ? 'collapsed' : 'w-64'}`}>
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
        
        <nav className="space-y-4 mb-12 flex-1">
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
      <main className={`flex-1 main-content p-4 lg:p-12 ${sidebarCollapsed ? 'lg:ml-24' : 'lg:ml-72'}`}>
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
    <header className="flex flex-col md:flex-row justify-between items-start md:items-center mb-16 gap-4">
      <div>
        <h1 className="text-4xl font-bold mb-2">Witaj, Jakub</h1>
        <p className="text-slate-400">Twoje imperium bukmacherskie jest online.</p>
      </div>
      <div className="glass-card px-10 py-6 flex items-center gap-5 border-indigo-500/20 bg-indigo-500/5">
        <div className="p-4 bg-indigo-500/20 rounded-2xl">
          <Wallet className="text-indigo-400" size={28} />
        </div>
        <div>
          <p className="text-xs text-slate-400 uppercase tracking-widest font-bold mb-1">Dostępny Balans</p>
          <p className="text-3xl font-bold text-white leading-none">
            {status?.bankroll?.toFixed(2)} <span className="text-lg font-normal text-indigo-300">PLN</span>
          </p>
        </div>
      </div>
    </header>

    <section className="grid grid-cols-1 md:grid-cols-3 gap-8 mb-16">
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

    <section className="glass-card p-10 mb-16">
      <h2 className="text-xl font-bold mb-10 flex items-center gap-2">
        <TrendingUp size={24} className="text-indigo-400" /> Progresja Bankrolla
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
      <div className="flex justify-between items-center mb-10">
        <h2 className="text-2xl font-bold">Najnowsze Predykcje</h2>
        <button onClick={onSeeAll} className="btn-see-all">
          Zobacz historię <ChevronRight size={16} />
        </button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
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
    <div className="grid grid-cols-1 gap-6">
      {coupons.length > 0 ? coupons.map((c, i) => (
        <div key={c.id} className="glass-card p-6 flex flex-col md:flex-row justify-between items-center gap-6">
          <div className="flex items-center gap-4">
            <div className={`w-12 h-12 rounded-full flex items-center justify-center ${c.status === 'WON' ? 'bg-emerald-500/10 text-emerald-400' : c.status === 'LOST' ? 'bg-rose-500/10 text-rose-400' : 'bg-amber-500/10 text-amber-400'}`}>
              {c.status === 'WON' ? <CheckCircle2 /> : c.status === 'LOST' ? <XCircle /> : <Clock />}
            </div>
            <div>
              <p className="font-bold text-lg">Kupon #{c.id} - {c.phase.toUpperCase()}</p>
              <p className="text-sm text-slate-500">{c.created_at}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-8 text-center">
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-widest">Kurs</p>
              <p className="font-bold">@{c.total_odds.toFixed(2)}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-widest">Stawka</p>
              <p className="font-bold">{c.stake_pln} PLN</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-widest">Wypłata</p>
              <p className={`font-bold ${c.status === 'WON' ? 'text-emerald-400' : 'text-slate-500'}`}>{c.payout_pln ? `${c.payout_pln} PLN` : '---'}</p>
            </div>
          </div>
        </div>
      )) : (
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
    <div className="mb-12">
      <h1 className="text-4xl font-bold mb-2">Ustawienia Bota</h1>
      <p className="text-slate-400">Konfiguracja parametrów analitycznych i finansowych.</p>
    </div>
    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
      <div className="glass-card p-8">
        <h3 className="text-lg font-bold mb-6 flex items-center gap-2"><Settings size={18} /> Algorytm & Ryzyko</h3>
        <div className="space-y-6">
          <ConfigItem label="Wersja Systemu" value={config?.version || "N/A"} />
          <ConfigItem label="Próg Pewniaczka" value={`${config?.pewniaczek_prog || 0}%`} />
          <ConfigItem label="Próg Kandydatów" value={`${(config?.min_confidence * 100).toFixed(0) || 0}%`} />
          <ConfigItem label="Fractional Kelly" value={`f*/${config?.kelly_fraction || 0}`} />
        </div>
      </div>
      <div className="glass-card p-8 text-center flex flex-col items-center justify-center">
        <div className="p-6 bg-indigo-500/10 rounded-full mb-6">
          <Info size={48} className="text-indigo-400" />
        </div>
        <p className="text-slate-400 mb-6 px-4">Parametry te są obecnie odczytywane z pliku `config.py`. Zmiana ustawień przez Dashboard będzie dostępna w kolejnej wersji.</p>
        <button className="btn-primary w-full opacity-50 cursor-not-allowed">Zapisz ustawienia</button>
      </div>
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
    className="glass-card overflow-hidden group hover:border-indigo-500/30 transition-all font-inter"
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
    <div className="p-6 space-y-6">
      {coupon.legs.map((leg, i) => (
        <div key={i} className="flex justify-between items-start">
          <div className="flex-1">
            <p className="text-sm font-bold text-slate-200">{leg.home} - {leg.away}</p>
            <p className="text-xs text-slate-500 flex items-center gap-1 mt-1"><Info size={10} /> Typ: <span className="text-slate-300 font-medium">{leg.tip}</span></p>
          </div>
          <div className="text-sm font-bold bg-indigo-500/10 text-indigo-300 px-3 py-1 rounded-lg">@{leg.odds}</div>
        </div>
      ))}
    </div>
    <div className="px-6 py-5 bg-white/[0.04] flex justify-between items-center mt-auto border-t border-white/5">
      <div className="flex gap-10">
        <div>
          <p className="text-[10px] text-slate-500 uppercase tracking-widest font-bold mb-1">Kurs</p>
          <p className="text-2xl font-bold text-white tracking-tighter">{coupon.total_odds.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-[10px] text-slate-500 uppercase tracking-widest font-bold mb-1">Stawka</p>
          <p className="text-2xl font-bold text-indigo-400 tracking-tighter">{coupon.stake_pln} <span className="text-xs">PLN</span></p>
        </div>
      </div>
      <div className="text-right">
        <div className={`text-xs font-bold px-4 py-2 rounded-xl ${coupon.status === 'WON' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-white/5 text-slate-500'}`}>
          {coupon.status === 'WON' ? 'ZWROT: ' + coupon.payout_pln + ' PLN' : coupon.status}
        </div>
      </div>
    </div>
  </motion.div>
);

const ConfigItem = ({ label, value }) => (
  <div className="flex justify-between items-center py-2 border-b border-white/5">
    <span className="text-slate-400">{label}</span>
    <span className="font-bold text-slate-200">{value}</span>
  </div>
);

export default App;
