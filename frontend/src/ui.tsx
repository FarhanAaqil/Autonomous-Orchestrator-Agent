import type { ReactNode, FormEvent } from 'react';
import { pretty } from './api';
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
