import { useCallback, useEffect, useState } from 'react';
import type { ReactNode, FormEvent } from 'react';
import { request, pretty } from './api';
export function useResource<T>(path: string, initial: T, tick = 0) {
  const [data, setData] = useState(initial); const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion(v => v + 1), []);
  useEffect(() => {
    const controller = new AbortController(); let active = true;
    setLoading(true); setError('');
    request<T>(path, 'GET', undefined, controller.signal).then(value => {if (active) setData(value);})
      .catch(e => {if (active && e.name !== 'AbortError') setError(e.message);})
      .finally(() => {if (active) setLoading(false);});
    return () => {active = false; controller.abort();};
  }, [path, version, tick]);
  return {data, error, loading, reload};
}
export function useAction(reload?: () => void) {
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  async function act(path: string, method = 'POST', body?: unknown) {
    setBusy(true); setError(''); setNotice('');
    try { const result = await request<Record<string, unknown>>(path, method, body); reload?.(); setNotice('Saved.'); return result; }
    catch (e) {setError(e instanceof Error ? e.message : 'The request failed.'); return undefined;}
    finally {setBusy(false);}
  }
  return {act, busy, error, notice};
}
export function Banner({error, notice}: {error?: string; notice?: string}) {
  return <>{error && <p role="alert" className="banner error">{error}</p>}{notice && <p role="status" className="banner">{notice}</p>}</>;
}
export function Pill({value}: {value: string}) {return <span className={'pill state-' + value}>{value.replaceAll('_', ' ')}</span>;}
export function Empty({children}: {children: ReactNode}) {return <div className="empty"><span className="empty-symbol" aria-hidden="true">&#9671;</span><p>{children}</p></div>;}
export function Json({value}: {value: unknown}) {return <pre className="data-block">{pretty(value)}</pre>;}
export function PageHead({eyebrow, title, children}: {eyebrow: string; title: string; children?: ReactNode}) {return <header className="page-head"><div><p className="eyebrow">{eyebrow}</p><h1 tabIndex={-1} id="page-title">{title}</h1></div>{children}</header>;}
export function Field({label, name, type = 'text', value, required = true, placeholder, minLength}: {label: string; name: string; type?: string; value?: string; required?: boolean; placeholder?: string; minLength?: number}) {
  return <label>{label}<input name={name} type={type} defaultValue={value} required={required} placeholder={placeholder} minLength={minLength}/></label>;
}
export function Form({children, onSubmit, busy, label = 'Save'}: {children: ReactNode; onSubmit: (data: FormData) => Promise<unknown>; busy: boolean; label?: string}) {
  async function submit(e: FormEvent<HTMLFormElement>) {e.preventDefault(); await onSubmit(new FormData(e.currentTarget));}
  return <form onSubmit={submit} className="form-grid"><fieldset disabled={busy}>{children}<button className="primary" type="submit">{busy ? 'Working...' : label}</button></fieldset></form>;
}
export function Pager({offset, total, setOffset}: {offset: number; total: number; setOffset: (n: number) => void}) {return <div className="pager"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous</button><span>{total ? offset + 1 : 0}?{Math.min(offset + 20, total)} of {total}</span><button disabled={offset + 20 >= total} onClick={() => setOffset(offset + 20)}>Next</button></div>;}
