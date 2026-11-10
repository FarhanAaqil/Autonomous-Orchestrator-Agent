import { useAction, useResource } from './hooks';
import { useEffect, useState } from 'react';
import type { Approval, Job, Page } from './api';
import { pretty } from './api';
import type { Props } from './pages';
import { Banner, Empty, Field, Form, Json, PageHead, Pager, Pill } from './ui';
export function Jobs({user, tick}: Props) {
  const [offset, setOffset] = useState(0); const [filter, setFilter] = useState(''); const [selected, setSelected] = useState('');
  const list = useResource<Page<Job>>('/jobs?limit=20&offset=' + offset + (filter ? '&status=' + filter : ''), {items: [], total: 0, limit: 20, offset: 0}, tick);
  const action = useAction(list.reload);
  return <><PageHead eyebrow="FROM INTENTION TO OUTCOME" title="Work in motion."/><Banner error={list.error || action.error} notice={action.notice}/>
    {user.role !== 'viewer' && <details className="panel"><summary>Create a job</summary><Form busy={action.busy} label="Queue job" onSubmit={f => action.act('/jobs', 'POST', {agent: f.get('agent'), goal: f.get('goal')})}><Field label="Agent identifier" name="agent" value="general_chat_agent"/><Field label="Goal" name="goal" placeholder="Describe a concrete outcome"/></Form></details>}
    <div className="toolbar"><label>Job status<select value={filter} onChange={e => {setFilter(e.target.value); setOffset(0);}}><option value="">All states</option>{['queued','running','awaiting_approval','awaiting_input','succeeded','failed','cancelled','expired'].map(s => <option key={s}>{s}</option>)}</select></label><button onClick={list.reload}>Refresh</button></div>
    <section className="panel">{list.loading && <p role="status">Loading work...</p>}{!list.loading && !list.data.items.length && <Empty>No jobs in this view.</Empty>}{list.data.items.map(job => <article className="list-row" key={job.id}><div><button className="text-button" onClick={() => setSelected(job.id)}>{job.goal}</button><small>{job.agent} ? {job.step_count}/{job.max_steps} steps ? {job.tokens_used}/{job.token_budget} tokens</small></div><Pill value={job.status}/></article>)}<Pager offset={offset} total={list.data.total} setOffset={setOffset}/></section>
    {selected && <JobDetail key={selected} id={selected} user={user} tick={tick} onClose={() => setSelected('')}/>}
  </>;
}
export function JobDetail({id, user, tick, onClose}: {id: string; user: Props['user']; tick: number; onClose?: () => void}) {
  const job = useResource<Job | null>('/jobs/' + id, null, tick);
  const steps = useResource<unknown[]>('/jobs/' + id + '/steps', [], tick);
  const action = useAction(() => {job.reload(); steps.reload();});
  let runId = '';
  try {runId = job.data?.result_json ? JSON.parse(job.data.result_json).run_id || '' : '';} catch { /* Raw result still renders below. */ }
  return <section className="panel detail"><div className="section-title"><h2>Job detail</h2>{onClose && <button onClick={onClose}>Close detail</button>}</div><Banner error={job.error || steps.error || action.error}/>{job.data && <><h3>{job.data.goal}</h3><Pill value={job.data.status}/><p className="small">Job {id}</p>{job.data.error && <p className="banner error">{job.data.error}</p>}{job.data.result_json && <Json value={job.data.result_json}/>}
    {user.role !== 'viewer' && ['queued','running','awaiting_approval','awaiting_input'].includes(job.data.status) && <button disabled={action.busy} onClick={() => action.act('/jobs/' + id + '/cancel')}>Cancel job</button>}
    {user.role !== 'viewer' && job.data.status === 'awaiting_input' && <Form busy={action.busy} label="Send answer" onSubmit={f => action.act('/jobs/' + id + '/answer', 'POST', {answer: f.get('answer')})}><Field label="Your answer" name="answer"/></Form>}
    <h3>Execution steps</h3>{steps.data.length ? steps.data.map((s, i) => <details key={i}><summary>Step {i + 1}</summary><Json value={s}/></details>) : <p className="muted">No recorded steps yet.</p>}{runId && <RunDetail id={runId}/>}</>}</section>;
}
function RunDetail({id}: {id: string}) {const run = useResource<unknown>('/runs/' + encodeURIComponent(id), null); return <><h3>Pipeline result</h3><Banner error={run.error}/><Json value={run.data}/></>;}
const states = ['pending','approved','rejected','executing','simulated','submitted','confirmed','failed','outcome_unknown','expired','superseded','executed'];
export function Approvals({user, tick}: Props) {
  const [filter, setFilter] = useState('pending'); const [offset, setOffset] = useState(0); const [selected, setSelected] = useState('');
  const list = useResource<Page<Approval>>('/approvals?limit=20&offset=' + offset + (filter ? '&status=' + filter : ''), {items: [], total: 0, limit: 20, offset: 0}, tick);
  return <><PageHead eyebrow="YOUR DECISION, ALWAYS" title="A moment for review."/><p className="intro">Review the exact content, destination, and execution mode before giving consent.</p><Banner error={list.error}/>
    <div className="toolbar"><label>Approval status<select value={filter} onChange={e => {setFilter(e.target.value); setOffset(0);}}><option value="">All states</option>{states.map(s => <option key={s}>{s}</option>)}</select></label><button onClick={list.reload}>Refresh</button></div>
    <section className="panel">{list.loading && <p role="status">Loading approvals...</p>}{!list.loading && !list.data.items.length && <Empty>Nothing waiting here. Your agents will bring proposals to you.</Empty>}{list.data.items.map(a => <div className="list-row" key={a.id}><div><button className="text-button" onClick={() => setSelected(a.id)}>{a.action_type.replaceAll('_', ' ')}</button><small>{a.target || a.source_agent || 'Agent proposal'} ? {a.execution_mode}</small></div><Pill value={a.status}/></div>)}<Pager offset={offset} total={list.data.total} setOffset={setOffset}/></section>
    {selected && <Review key={selected} id={selected} user={user} close={() => {setSelected(''); list.reload();}}/>}</>;
}
function Review({id, user, close}: {id: string; user: Props['user']; close: () => void}) {
  // Keep this reviewed snapshot stable; a changed server hash must reject consent.
  const approval = useResource<Approval | null>('/approvals/' + id, null);
  const audit = useResource<unknown[]>('/approvals/' + id + '/audit', []);
  const attempts = useResource<unknown[]>('/approvals/' + id + '/attempts', []);
  const [checked, setChecked] = useState(false); const a = approval.data;
  const action = useAction(() => {approval.reload(); audit.reload(); attempts.reload(); setChecked(false);});
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer);}, []);
  const expired = a?.expires_at ? Date.parse(a.expires_at) <= now : false;
  return <section className="panel review"><div className="section-title"><h2>Review proposal</h2><button onClick={close}>Close review</button></div><Banner error={approval.error || audit.error || attempts.error || action.error} notice={action.notice}/>
    {a && <><div className="review-facts"><div><small>Action</small><strong>{a.action_type}</strong></div><div><small>Destination</small><strong>{a.target || 'See payload below'}</strong></div><div><small>Mode</small><strong>{a.execution_mode}</strong></div><div><small>Expires</small><strong>{a.expires_at ? new Date(a.expires_at).toLocaleString() : 'No expiry supplied'}</strong></div></div><Pill value={a.status}/><h3>Exact proposed content</h3><Json value={a.payload_json}/><details><summary>Content fingerprint and conversation</summary><p className="hash">{a.payload_hash}</p><p className="hash">{a.session_id || 'No conversation attached'}</p></details>
      {a.execution_mode === 'simulation' && <p className="banner">Simulation: no external delivery will occur. A simulated result is not confirmation of a real action.</p>}
      {['submitted','outcome_unknown'].includes(a.status) && <p className="banner">Delivery is not confirmed. Inspect the execution evidence before reconciling; do not blindly retry.</p>}
      {user.role === 'viewer' ? <p className="banner">Viewer access: only operators and administrators can decide or execute.</p> : <><fieldset disabled={action.busy}>{a.status === 'pending' && <><label className="check"><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)}/>I reviewed this exact content, destination, and mode.</label><div className="actions"><button className="primary" disabled={!checked || !a.payload_hash || expired} onClick={() => action.act('/approvals/' + id + '/approve', 'POST', {expected_hash: a.payload_hash, session_id: a.session_id})}>Approve reviewed content</button><button onClick={() => action.act('/approvals/' + id + '/reject')}>Reject proposal</button></div></>}
      {a.status === 'approved' && <button className="primary" disabled={expired} onClick={() => action.act('/approvals/' + id + '/execute')}>Execute approved action</button>}</fieldset>
      {a.status === 'pending' && <details><summary>Revise and request a new review</summary><Form busy={action.busy} label="Create revised proposal" onSubmit={async f => {let payload: unknown; try {payload = JSON.parse(String(f.get('payload')));} catch {return;} const result = await action.act('/approvals/' + id + '/edit', 'POST', {payload, target: f.get('target') || null}); if (result) close();}}><Field label="Destination" name="target" value={a.target || ''} required={false}/><label>JSON payload<textarea name="payload" defaultValue={pretty(a.payload_json)} rows={8} required onChange={e => {try {JSON.parse(e.target.value); e.target.setCustomValidity('');} catch {e.target.setCustomValidity('Enter valid JSON.');}}}/></label></Form></details>}
      {['submitted','outcome_unknown'].includes(a.status) && <Form busy={action.busy} label="Record verified outcome" onSubmit={f => action.act('/approvals/' + id + '/reconcile', 'POST', {outcome: f.get('outcome'), evidence: f.get('evidence')})}><label>Verified outcome<select name="outcome"><option value="confirmed">Confirmed</option><option value="failed">Failed</option></select></label><Field name="evidence" label="Provider evidence or reference"/></Form>}</>}
      <details><summary>Execution evidence ({attempts.data.length})</summary><Json value={attempts.data}/></details><details><summary>Audit history ({audit.data.length})</summary><Json value={audit.data}/></details>
    </>}
  </section>;
}
