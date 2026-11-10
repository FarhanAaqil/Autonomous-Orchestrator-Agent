import { useEffect, useRef, useState } from 'react';
import { motion, MotionConfig, useReducedMotion } from 'motion/react';
import { ArrowUpRight, Boxes, CalendarDays, CheckCheck, CircleHelp, FlaskConical, LayoutDashboard, LogOut, MessageSquare, Settings2, Sprout, Workflow } from 'lucide-react';
import { request, setSession, subscribe } from './api';
import type { Session } from './api';
import { Banner } from './ui';
import { Overview, Chat, Jobs, Approvals, Schedules, Memories, Pipelines, Evaluation, Settings } from './pages';
const navigation = [
  ['Overview', LayoutDashboard], ['Chat', MessageSquare], ['Jobs', Boxes],
  ['Approvals', CheckCheck], ['Schedules', CalendarDays], ['Memory', Sprout],
  ['Pipelines', Workflow], ['Evaluation', FlaskConical], ['Settings', Settings2],
] as const;
export default function App() {
  const reduceMotion = useReducedMotion();
  const [session, updateSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const [tab, setTab] = useState('Overview'); const [status, setStatus] = useState('Connecting'); const [tick, setTick] = useState(0);
  const main = useRef<HTMLElement>(null);
  function signedIn(value: Session) {setSession(value); updateSession(value); setError('');}
  useEffect(() => {
    let active = true;
    request<Session>('/auth/session').then(value => {if (active) signedIn(value);})
      .catch(e => {if (active && e.status !== 401) setError('Cannot reach your workspace. Check the service and retry.');})
      .finally(() => {if (active) setLoading(false);});
    const expire = () => {setSession(null); updateSession(null); setError('Your session ended. Sign in to continue.');};
    window.addEventListener('session-expired', expire);
    return () => {active = false; window.removeEventListener('session-expired', expire);};
  }, []);
  useEffect(() => {
    if (!session) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const stop = subscribe(() => {if (!timer) timer = setTimeout(() => {setTick(t => t + 1); timer = undefined;}, 500);}, setStatus);
    const poll = setInterval(() => {if (!document.hidden) setTick(t => t + 1);}, 15000);
    return () => {stop(); clearInterval(poll); clearTimeout(timer);};
  }, [session]);
  function navigate(next: string) {setTab(next); requestAnimationFrame(() => main.current?.querySelector<HTMLElement>('h1')?.focus());}
  async function logout() {
    try {await request('/auth/logout', 'POST'); setSession(null); updateSession(null); setTab('Overview'); setError('');}
    catch {setError('Could not sign out. Please retry while connected.');}
  }
  const [signingIn, setSigningIn] = useState(false);
  if (loading) return <div className="center"><span role="status">Opening your workspace...</span></div>;
  if (!session) return <div className="login-shell">
    <section className="login-story"><div className="brand"><span className="brand-mark">t.</span> toji<span className="small">WORKSPACE</span></div>
      <p className="eyebrow">A little structure. More possibility.</p><h1>Make room<br/>for your<br/><em>next idea.</em></h1>
      <p>Your agents, their work, and the decisions that stay yours. All in one considered space.</p>
      <div className="sculpture" aria-hidden="true"><i/><i/><i/><span>YOU ? IDEAS ? ACTION</span></div>
      <p className="small">Thoughtful automation. Human direction.</p>
    </section>
    <section className="login-panel"><span className="kicker">YOUR PERSONAL CONTROL ROOM</span><h2>Welcome back.</h2><p>Sign in to pick up where you left off.</p>
      <Banner error={error}/>
      <form onSubmit={async e => {e.preventDefault(); const f = new FormData(e.currentTarget); setSigningIn(true); setError('');
        try {signedIn(await request<Session>('/auth/login', 'POST', {username: f.get('username'), password: f.get('password')}));}
        catch {setError('Unable to sign in. Check your credentials or wait a few minutes before retrying.');}
        finally {setSigningIn(false);}
      }}>
        <label>Username<input name="username" autoComplete="username" required autoFocus maxLength={100}/></label>
        <label>Password<input name="password" type="password" autoComplete="current-password" required maxLength={1024}/></label>
        <button className="primary" disabled={signingIn}>{signingIn ? 'Signing in...' : 'Enter workspace'}<ArrowUpRight size={18}/></button>
      </form><p className="small"><CircleHelp size={14}/> Accounts are managed by your workspace administrator.</p>
    </section>
  </div>;
  const props = {user: session.user, tick, navigate};
  const content = tab === 'Overview' ? <Overview {...props}/> : tab === 'Chat' ? <Chat {...props}/> : tab === 'Jobs' ? <Jobs {...props}/> : tab === 'Approvals' ? <Approvals {...props}/> : tab === 'Schedules' ? <Schedules {...props}/> : tab === 'Memory' ? <Memories {...props}/> : tab === 'Pipelines' ? <Pipelines {...props}/> : tab === 'Evaluation' ? <Evaluation {...props}/> : <Settings {...props}/>;
  return <MotionConfig reducedMotion="user"><a href="#workspace" className="skip">Skip to workspace</a><div className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-mark">t.</span> toji<span className="small">WORKSPACE</span></div>
      <div className="workspace-name"><span className="workspace-icon">P</span><div>Personal workspace<small>Shared with your team</small></div></div>
      <p className="nav-label">YOUR WORKSPACE</p><nav aria-label="Main navigation">{navigation.map(([name, Icon]) => <button key={name} onClick={() => navigate(name)} aria-current={tab === name ? 'page' : undefined}><Icon size={18}/>{name}</button>)}</nav>
      <div className="sidebar-bottom"><div className="connection"><span className={status === 'Live' ? 'live-dot' : 'wait-dot'}/>{status} updates</div><div className="account"><span className="avatar">{session.user.username.slice(0, 1).toUpperCase()}</span><div>{session.user.username}<small>{session.user.role}</small></div><button title="Sign out" aria-label="Sign out" onClick={logout}><LogOut size={17}/></button></div></div>
    </aside><div className="workspace-body"><header className="topbar"><span>Workspace <span className="muted">/ {tab}</span></span><span className="small">YOUR IDEAS. YOUR DIRECTION.</span></header>
      <main id="workspace" ref={main}><Banner error={error}/><motion.div key={tab} initial={reduceMotion ? false : {opacity: 0, y: 6}} animate={{opacity: 1, y: 0}} transition={{duration: .18}}>{content}</motion.div></main>
      <footer>Toji ? A considered space for autonomous work.<span>Human approval stays at the center.</span></footer>
    </div></div></MotionConfig>;
}
