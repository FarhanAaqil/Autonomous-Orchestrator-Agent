'use strict';
function apiOrigin(value = 'http://127.0.0.1:8080') {
  const url = new URL(value);
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/') throw new Error('Use a plain API origin without credentials, query or path.');
  if (!(url.protocol === 'https:' || (url.protocol === 'http:' && ['127.0.0.1','localhost','[::1]'].includes(url.hostname)))) throw new Error('Use HTTPS, or HTTP on loopback for local development.');
  return url.origin;
}
function healthy(body) {return body?.service === 'toji-orchestrator' && body.status === 'ok' && typeof body.version === 'string' && /^\d+\.\d+\.\d+/.test(body.version);}
function internal(target, origin) {try {return new URL(target).origin === origin;} catch {return false;}}
function external(target) {try {const u = new URL(target);const root = '/FarhanAaqil/orchestrator_agent';return u.protocol === 'https:' && !u.username && !u.password && u.hostname === 'github.com' && (u.pathname === root || u.pathname.startsWith(root + '/'));} catch {return false;}}
module.exports = {apiOrigin, healthy, internal, external};
