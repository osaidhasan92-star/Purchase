/* Shared database transport. Business records and credentials are never cached in LocalStorage. */
const BackendPersistence = (() => {
  let csrf = '';
  let queue = Promise.resolve();
  let pending = 0;
  let failed = false;
  const revisions = {}, baselines = {};

  function status(message, error = false) {
    let el = document.getElementById('server-save-status');
    if (!el) {
      el = document.createElement('div');
      el.id = 'server-save-status';
      el.setAttribute('role', 'status');
      el.style.cssText = 'position:fixed;bottom:12px;left:12px;z-index:10000;padding:10px 16px;border-radius:8px;font:13px Arial;max-width:70vw';
      document.body.appendChild(el);
    }
    el.style.background = error ? '#991b1b' : '#164e63';
    el.style.color = '#fff';
    el.textContent = message;
    if (error) {
      const button = document.createElement('button');
      button.textContent = 'Reload server records';
      button.style.marginLeft = '12px';
      button.onclick = () => location.reload();
      el.appendChild(button);
    }
    if (!error && !pending) setTimeout(() => { if (!pending && !failed) el.remove(); }, 2500);
  }

  async function request(path, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const headers = new Headers(options.headers || {});
    if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
    if (!['GET', 'HEAD'].includes(method) && csrf) headers.set('X-CSRF-Token', csrf);
    const response = await fetch('/api' + path, {...options, method, headers, credentials: 'same-origin', cache: 'no-store'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.error || `Request failed (${response.status})`);
      error.status = response.status;
      if (response.status === 401 && path !== '/auth/login' && !location.pathname.endsWith('index.html')) location.href = 'index.html';
      throw error;
    }
    if (data.csrfToken) csrf = data.csrfToken;
    if (method === 'GET' && (path === '/state' || path === '/hr/state')) {
      const name = path === '/state' ? 'app' : 'hr';
      revisions[name] = data.revision;
      baselines[name] = structuredClone(data.state);
      return data.state;
    }
    return data;
  }

  function accept(name, state) { baselines[name] = structuredClone(state); }
  function save(name, state) {
    const snapshot = structuredClone(state);
    pending += 1;
    status('Saving to server…');
    const work = queue.then(async () => {
      if (failed) throw new Error('A previous save failed. Reload server records before continuing.');
      const changes = {};
      Object.keys(snapshot).forEach(key => {
        if (key === 'users' || key === 'activities') return;
        if (JSON.stringify(snapshot[key]) !== JSON.stringify(baselines[name]?.[key])) changes[key] = snapshot[key];
      });
      if (Object.keys(changes).length) {
        const result = await request(name === 'app' ? '/state' : '/hr/state', {
          method: 'PATCH', body: JSON.stringify({revision: revisions[name], changes})
        });
        revisions[name] = result.revision;
        baselines[name] = snapshot;
      }
    });
    queue = work.catch(error => {
      failed = true;
      status('NOT SAVED: ' + error.message, true);
      throw error;
    }).finally(() => {
      pending -= 1;
      if (!failed) status(pending ? 'Saving to server…' : 'Saved to server');
    });
    queue.catch(() => {}); // Errors remain visible; drain() still rejects and blocks navigation.
    return queue;
  }

  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || (!pending && !failed) || event.ctrlKey || event.metaKey || link.target === '_blank') return;
    event.preventDefault();
    queue.then(() => location.assign(link.href)).catch(() => {});
  }, true);
  window.addEventListener('beforeunload', event => {
    if (pending || failed) { event.preventDefault(); event.returnValue = ''; }
  });
  return {request, save, accept, drain: () => queue};
})();
