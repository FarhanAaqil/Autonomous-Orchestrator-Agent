import { useEffect, useState } from 'react';
import { request } from './api';
import type { Session } from './api';
import { Banner } from './ui';

type Mode = 'login' | 'register' | 'forgot' | 'verify' | 'reset';
export function AccountEntry({signedIn, initialError}: {signedIn: (value: Session) => void; initialError: string}) {
  const [link] = useState(() => new URLSearchParams(window.location.hash.slice(1)));
  const [mode, setMode] = useState<Mode>(() => link.get('action') === 'verify' ? 'verify' : link.get('action') === 'reset' ? 'reset' : 'login');
  const [enabled, setEnabled] = useState(false);
  const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (link.has('token')) window.history.replaceState(null, '', window.location.pathname);
    request<{registration: boolean}>('/auth/options').then(value => setEnabled(value.registration)).catch(() => setEnabled(false));
  }, [link]);
  function navigate(next: Mode) {setMode(next); setError(''); setNotice('');}
  const title = {login: 'Welcome back.', register: 'Make space for your ideas.', forgot: 'Recover your account.', verify: 'Confirm your email.', reset: 'Choose a new password.'}[mode];
  return <section className="login-panel"><span className="kicker">YOUR PERSONAL CONTROL ROOM</span><h2>{title}</h2>
    <Banner error={error || initialError} notice={notice}/>
    <form onSubmit={async e => {
      e.preventDefault(); const data = new FormData(e.currentTarget); setBusy(true); setError(''); setNotice('');
      try {
        if (mode === 'login') signedIn(await request<Session>('/auth/login', 'POST', {username: data.get('email'), password: data.get('password')}));
        else if (mode === 'register' || mode === 'forgot') {
          const result = await request<{message: string}>(mode === 'register' ? '/auth/register' : '/auth/password/reset/request', 'POST', {email: data.get('email'), ...(mode === 'register' ? {password: data.get('password')} : {})});
          setNotice(result.message);
        } else {
          await request(mode === 'verify' ? '/auth/verify' : '/auth/password/reset/confirm', 'POST', {token: link.get('token'), ...(mode === 'reset' ? {password: data.get('password')} : {})});
          setMode('login'); setNotice(mode === 'verify' ? 'Email verified. You can sign in now.' : 'Password changed. Sign in with your new password.');
        }
      } catch (reason) {setError(reason instanceof Error ? reason.message : 'Unable to complete this request. Please retry.');}
      finally {setBusy(false);}
    }}>
      {['login', 'register', 'forgot'].includes(mode) && <label>{mode === 'login' ? 'Email or administrator username' : 'Email'}<input name="email" type={mode === 'login' ? 'text' : 'email'} autoComplete="username" maxLength={100} required/></label>}
      {['login', 'register', 'reset'].includes(mode) && <label>Password<input name="password" type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} minLength={mode === 'login' ? 1 : 14} maxLength={1024} required/></label>}
      {mode === 'verify' && <p>Confirm that this email address belongs to you.</p>}
      <button className="primary" disabled={busy}>{busy ? 'Working...' : {login: 'Enter workspace', register: 'Create account', forgot: 'Send reset link', verify: 'Verify email', reset: 'Reset password'}[mode]}</button>
    </form>
    <div className="actions">{mode !== 'login' && <button onClick={() => navigate('login')}>Back to sign in</button>}{enabled && mode === 'login' && <><button onClick={() => navigate('register')}>Sign up</button><button onClick={() => navigate('forgot')}>Forgot password?</button></>}</div>
    {!enabled && <p className="small">Accounts are managed by your workspace administrator.</p>}
  </section>;
}
