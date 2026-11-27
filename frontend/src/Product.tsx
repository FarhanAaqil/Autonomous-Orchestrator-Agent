import { useResource } from './hooks';
import { Banner } from './ui';

export function Pricing() {
  type Plans = {plans: Record<string, {runs_per_day: number; active_schedules: number; connected_accounts: number; daily_tokens: number; monthly_tokens: number}>; payment_url: string | null; payment_note: string};
  const options = useResource<Plans | null>('/auth/plans', null);
  return <section className="panel"><h2>Choose room to grow.</h2><Banner error={options.error}/>{options.data && <><div className="card-list">{Object.entries(options.data.plans).map(([name, plan]) => <article key={name}><h3>{name === 'pro' ? 'Pro' : 'Free'}</h3><p>{plan.runs_per_day} runs a day, {plan.active_schedules} active schedules, {plan.connected_accounts} connections.</p><p>{plan.daily_tokens.toLocaleString()} model tokens a day, {plan.monthly_tokens.toLocaleString()} a month.</p></article>)}</div><p className="small">{options.data.payment_note}</p>{options.data.payment_url ? <a className="primary" href={options.data.payment_url} target="_blank" rel="noopener noreferrer">View payment details & upgrade</a> : <p className="small">Paid upgrades are not available until the administrator configures a payment link.</p>}</>}</section>;
}

export function ProductInfo() {
  return <><section className="panel"><h2>Turn a brief into work you can review.</h2><p>Research a question, prepare a career document, or draft a publication. Follow each job and review supported external actions before execution.</p><p>New accounts start in simulation. Connect your own provider in Settings, try one task, then inspect its approval card. Simulation does not send or publish.</p></section><Pricing/><PolicyDrafts/></>;
}

export function PolicyDrafts() {
  return <section className="panel"><h2>Service policies</h2><p><strong>DRAFT: needs human review</strong></p><p className="small">These drafts are incomplete operating policies, not legal advice. Operator identity, contact, retention periods, jurisdiction and payment terms must be settled before public launch.</p>
    <details><summary>Terms draft</summary><p>You are responsible for reviewing generated work and authorizing external actions. Model output can be wrong. Provider availability and plan limits may restrict work. Payment activates a plan only after administrator confirmation; paid access ends on the stated expiry date. Refund and cancellation terms require operator review before sales begin.</p></details>
    <details><summary>Privacy draft</summary><p>The service stores account details, conversations, jobs, approvals, usage and encrypted provider credentials. Relevant task content is sent to the model and connected providers needed for your request. Administrators manage accounts and usage. Backup retention, deletion timelines and the privacy contact remain to be finalized. Do not submit sensitive information until these policies are reviewed.</p></details>
    <details><summary>Acceptable-use draft</summary><p>Use only accounts and content you are authorized to access. Do not send spam, impersonate others, evade consent, attack systems or submit unlawful content. Do not bypass usage limits or safety controls. Administrators may suspend misuse. Every supported send or publish action requires explicit approval.</p></details>
  </section>;
}
