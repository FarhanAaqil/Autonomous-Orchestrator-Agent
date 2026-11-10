import { useCallback, useEffect, useState } from 'react';
import { request } from './api';
export function useResource<T>(path: string, initial: T, tick = 0) {
  const [result, setResult] = useState({data: initial, error: '', key: ''});
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion(v => v + 1), []);
  const key = JSON.stringify([path, version, tick]);
  useEffect(() => {
    const controller = new AbortController(); let active = true;
    request<T>(path, 'GET', undefined, controller.signal)
      .then(data => {if (active) setResult({data, error: '', key});})
      .catch(e => {if (active && e.name !== 'AbortError') setResult(previous => ({...previous, error: e.message, key}));});
    return () => {active = false; controller.abort();};
  }, [path, key]);
  return {data: result.data, error: result.key === key ? result.error : '', loading: result.key !== key, reload};
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
