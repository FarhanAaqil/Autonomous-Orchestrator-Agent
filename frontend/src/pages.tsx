import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Layers3, Plus, Send, Square, RefreshCw } from 'lucide-react';
import { dispatch, request } from './api';
import type { Agent, Approval, Conversation, Job, Message, Page, User } from './api';
import { Banner, Empty, PageHead, Pill, useResource } from './ui';
export { Jobs, Approvals } from './work';
export { Schedules, Memories, Pipelines, Evaluation, Settings } from './manage';
export type Props = {user: User; tick: number; navigate: (tab: string) => void};
const Graph = lazy(() => import('./Graph'));
export function Overview({user, tick, navigate}: Props) {
  const jobs = useResource<Page<Job>>('/jobs?limit=5', {items: [], total: 0, limit: 5, offset: 0}, tick);
  const approvals = useResource<Page<Approval>>('/approvals?status=pending&limit=5', {items: [], total: 0, limit: 5, offset: 0}, tick);
  const agents = useResource<Agent[]>('/agents', [], tick);
  const ready = useResource<Record<string, boolean>>('/ready', {}, tick);
  const flags = useResource<{key: string; value: string}[]>('/system/flags', [], tick);
  const paused = flags.data.find(f => f.key === 'kill_switch')?.value === 'on';
  const [graph, setGraph] = useState(false);
  const [calm, setCalm] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(() => {const media = matchMedia('(prefers-reduced-motion: reduce)'); const change = () => setCalm(media.matches); media.addEventListener('change', change); return () => media.removeEventListener('change', change);}, []);
  return <><PageHead eyebrow="A FRESH PERSPECTIVE" title={'Hello, ' + user.username + '.'}><button onClick={() => navigate('Chat')} className="primary">Start a conversation <Plus size={17}/></button></PageHead>
    <Banner error={jobs.error || approvals.error || agents.error || flags.error}/>
    <section className="welcome-panel"><div><span className="eyebrow">SPACE TO THINK. TOOLS TO DO.</span><h2>Good work starts<br/>with a little <em>direction.</em></h2><p>Give your agents an idea. Follow their progress.<br/>Make the decisions that matter.</p><button onClick={() => navigate('Jobs')}>Explore your work <ArrowUpRight size={17}/></button></div><div className="orbit-art" aria-hidden="true"><div className="orbit outer"/><div className="orbit inner"/><span className="orbit-center">t.</span><i className="satellite s1">?</i><i className="satellite s2">?</i><i className="satellite s3">?</i></div></section>
    <div className="stats"><button onClick={() => navigate('Jobs')}><span>Work in your queue</span><strong>{jobs.loading ? '?' : jobs.data.total}</strong><small>All saved jobs <ArrowUpRight size={15}/></small></button><button onClick={() => navigate('Approvals')}><span>Waiting for your review</span><strong>{approvals.loading ? '?' : approvals.data.total}</strong><small>Your approval matters <ArrowUpRight size={15}/></small></button><button onClick={() => navigate('Settings')}><span>Workspace status</span><strong className="word">{paused ? 'Paused' : flags.loading ? 'Checking' : 'Active'}</strong><small>{paused ? 'Automation is on hold' : 'Review controls in settings'} <ArrowUpRight size={15}/></small></button></div>
    <div className="section-title"><div><p className="eyebrow">A SMALL TEAM. MANY POSSIBILITIES.</p><h2>Your agent studio</h2></div><button disabled={calm} aria-pressed={graph} onClick={() => setGraph(!graph)}><Layers3 size={16}/>{graph ? 'Close 3D view' : 'Explore in 3D'}</button></div>
    {calm && <p className="small">Reduced motion is enabled. The complete agent list is available below.</p>}
    {graph && !calm && <Suspense fallback={<p role="status">Opening the optional 3D view?</p>}><Graph agents={agents.data}/></Suspense>}
    <div className="agent-grid">{agents.data.map((agent, i) => <article className="agent-card" key={agent.id}><span className={'agent-icon tone-' + i % 4}>{agent.name.slice(0, 1)}</span><Pill value={agent.is_active ? agent.status : 'disabled'}/><h3>{agent.name}</h3><p>{agent.description}</p><small>{agent.gated_capabilities.length ? 'Approval required for external actions' : 'Ready to explore ideas'}</small></article>)}</div>
    <div className="section-title"><h2>Recently in motion</h2><button onClick={() => navigate('Jobs')}>View all work <ArrowUpRight size={16}/></button></div>
    <section className="panel">{jobs.data.items.length ? jobs.data.items.map(j => <div className="list-row" key={j.id}><div><h3>{j.goal}</h3><small>{j.agent} ? {new Date(j.created_at).toLocaleString()}</small></div><Pill value={j.status}/></div>) : <Empty>Your next project starts here. Create a job or start a conversation.</Empty>}</section>
    <section className="service-strip" aria-label="Service readiness"><span>Behind the scenes</span>{Object.entries(ready.data).map(([name, ok]) => <span key={name}><i className={ok ? 'live-dot' : 'wait-dot'}/>{name}: {ok ? 'ready' : 'unavailable'}</span>)}{ready.error && <span role="alert">Some services are unavailable. Check diagnostics in Settings.</span>}</section>
  </>;
}
export function Chat({user}: Props) {
  const conversations = useResource<Conversation[]>('/conversations?limit=100', []);
  const [cid, setCid] = useState<string | null>(null); const [messages, setMessages] = useState<Message[]>([]);
  const [command, setCommand] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [answer, setAnswer] = useState(''); const [clarification, setClarification] = useState('');
  const controller = useRef<AbortController | null>(null); const end = useRef<HTMLDivElement>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function load(id: string) {
    controller.current?.abort(); setCid(id); setError(''); setAnswer(''); setClarification('');
    try {setMessages(await request<Message[]>('/conversations/' + id + '/messages?limit=500'));}
    catch (e) {setError((e as Error).message);}
  }
  async function send() {
    if (!command.trim() || busy) return;
    const text = command; setCommand(''); setBusy(true); setError(''); setAnswer(''); setClarification('');
    let current = cid;
    controller.current = new AbortController();
    try {
      if (!current) {const created = await request<Conversation>('/conversations', 'POST', {title: text.slice(0, 80)}); current = created.id; setCid(current);}
      setMessages(prev => [...prev, {id: crypto.randomUUID(), conversation_id: current!, role: 'user', content: text, created_at: new Date().toISOString()}]);
      await dispatch(text, current, (event, data) => {
        if (event === 'token') setAnswer(value => value + String(data.token || ''));
        if (event === 'clarification') setClarification(String(data.reasoning || 'Please clarify your request.') + ' ' + (Array.isArray(data.candidates) ? data.candidates.join(', ') : ''));
      }, controller.current.signal);
    } catch (e) {setError((e as Error).name === 'AbortError' ? 'Stopped waiting. Work already accepted by the server may continue; refresh the conversation before retrying.' : (e as Error).message);}
    finally {
      if (current) {try {setMessages(await request<Message[]>('/conversations/' + current + '/messages?limit=500')); setAnswer('');} catch { /* Retain visible output until the next refresh. */ }}
      setBusy(false); conversations.reload();
    }
  }
  return <><PageHead eyebrow="THINK OUT LOUD" title="A conversation, then a plan."><button disabled={busy} onClick={() => {setCid(null); setMessages([]); setAnswer(''); setError('');}}><Plus size={16}/>New conversation</button></PageHead>
    <div className="chat-layout"><aside className="panel conversation-list"><h3>Your conversations</h3><Banner error={conversations.error}/>{conversations.data.map(c => <button disabled={busy} aria-current={cid === c.id ? 'page' : undefined} onClick={() => load(c.id)} key={c.id}>{c.title}<small>{c.message_count} messages</small></button>)}{!conversations.data.length && <p className="muted">Your first conversation is a blank canvas.</p>}</aside>
    <section className="panel chat-panel"><Banner error={error} notice={clarification}/><div className="transcript" aria-label="Conversation messages">{!messages.length && <Empty>What would you like to move forward today?</Empty>}{messages.map(m => <article className={'message ' + m.role} key={m.id}><span className="eyebrow">{m.role === 'user' ? 'YOU' : m.agent || 'TOJI'}</span><p>{m.content}</p></article>)}{answer && <article className="message assistant"><span className="eyebrow">TOJI</span><p>{answer}</p></article>}<div ref={end}/></div>
      <div className="chat-tools"><button onClick={() => end.current?.scrollIntoView({behavior: 'auto', block: 'nearest'})}>Jump to latest</button>{cid && <button disabled={busy} onClick={() => load(cid)}><RefreshCw size={14}/>Refresh saved messages</button>}</div>
      {user.role !== 'viewer' ? <form className="composer" onSubmit={e => {e.preventDefault(); void send();}}><label htmlFor="command" className="sr-only">Your message</label><textarea id="command" value={command} onChange={e => setCommand(e.target.value)} placeholder="Give your next idea a place to begin?" rows={3} required disabled={busy}/><div><span className="small" role="status">{busy ? 'Working on your request?' : 'Actions that need consent will appear in Approvals.'}</span>{busy ? <button type="button" onClick={() => controller.current?.abort()}><Square size={15}/>Stop waiting</button> : <button className="primary" disabled={!command.trim()}><Send size={16}/>Send</button>}</div></form> : <p className="banner">Viewer access: you can read saved conversations.</p>}
    </section></div></>;
}
