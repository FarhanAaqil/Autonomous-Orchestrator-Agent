const {test} = require('node:test');
const assert = require('node:assert/strict');
const {apiOrigin, healthy, internal, external} = require('./endpoint');
test('one configured origin without embedded credentials', () => {
  assert.equal(apiOrigin(), 'http://127.0.0.1:8080');
  assert.equal(apiOrigin('http://localhost:8081'), 'http://localhost:8081');
  for (const url of ['http://example.com','https://user:secret@example.com','file:///tmp','https://example.com/path']) assert.throws(() => apiOrigin(url));
});
test('health identifies this service rather than any successful HTTP response', () => {
  assert.equal(healthy({status:'ok',version:'1.0.0'}), false);
  assert.equal(healthy({service:'toji-orchestrator',status:'ok',version:'1.0.0'}), true);
});
test('navigation and external targets stay within their allowlists', () => {
  assert.equal(internal('http://127.0.0.1:8080/ui','http://127.0.0.1:8080'),true);
  assert.equal(internal('https://evil.example','http://127.0.0.1:8080'),false);
  for (const url of ['javascript:alert(1)','file:///tmp','https://github.com.evil.example/FarhanAaqil/orchestrator_agent']) assert.equal(external(url),false);
});
