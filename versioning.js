(function () {
  const VERSION_CACHE_KEY = 'law-summary-eval.latest-version';
  const VERSION_CACHE_TTL_MS = 10 * 60 * 1000;
  const GITHUB_LATEST_COMMIT_URL = 'https://api.github.com/repos/Wayne-Jan/law-summary-eval/commits/main';
  const state = {
    version: new URLSearchParams(window.location.search).get('v') || '',
  };

  function readVersionCache() {
    try {
      const raw = window.localStorage.getItem(VERSION_CACHE_KEY);
      if (!raw) return null;
      const cached = JSON.parse(raw);
      if (!cached || typeof cached.version !== 'string' || typeof cached.ts !== 'number') return null;
      if (Date.now() - cached.ts > VERSION_CACHE_TTL_MS) return null;
      return cached.version;
    } catch {
      return null;
    }
  }

  function writeVersionCache(version) {
    try {
      window.localStorage.setItem(VERSION_CACHE_KEY, JSON.stringify({ version, ts: Date.now() }));
    } catch {
      // Ignore cache write failures.
    }
  }

  function setUrlVersion(version) {
    // Store version in state only; do not pollute the URL bar.
    if (!version) return;
    state.version = version;
    // Clean up any existing ?v= from the URL
    const url = new URL(window.location.href);
    if (url.searchParams.has('v')) {
      url.searchParams.delete('v');
      window.history.replaceState({}, '', url.pathname + (url.search || '') + url.hash);
    }
  }

  function versionedHref(href) {
    if (!href) return href;
    try {
      const url = new URL(href, window.location.href);
      if (url.origin !== window.location.origin) return href;
      if (!url.pathname.endsWith('.html')) return href;
      if (state.version) url.searchParams.set('v', state.version);
      return url.pathname + url.search + url.hash;
    } catch {
      return href;
    }
  }

  async function fetchLatestVersionFromGitHub() {
    const cached = readVersionCache();
    if (cached) return cached;
    try {
      const res = await fetch(GITHUB_LATEST_COMMIT_URL, {
        cache: 'no-store',
        headers: { Accept: 'application/vnd.github+json' },
      });
      if (!res.ok) return '';
      const data = await res.json();
      const version = String(data && data.sha ? data.sha : '').slice(0, 8);
      if (version) {
        writeVersionCache(version);
        return version;
      }
    } catch {
      // Fall back below.
    }
    return '';
  }

  function syncVersionedLinks(root = document) {
    root.querySelectorAll('a[href]').forEach((a) => {
      const href = a.getAttribute('href');
      if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;
      try {
        const url = new URL(href, window.location.href);
        if (url.origin !== window.location.origin || !url.pathname.endsWith('.html')) return;
      } catch {
        return;
      }
      a.setAttribute('href', versionedHref(href));
    });
  }

  async function loadSiteVersion() {
    try {
      let version = await fetchLatestVersionFromGitHub();
      if (!version) {
        const res = await fetch('./data/site_meta.json', { cache: 'no-store' });
        if (!res.ok) return state.version;
        const meta = await res.json();
        version = meta.version || meta.build_version || '';
      }
      if (version) {
        state.version = version;
        setUrlVersion(version);
        syncVersionedLinks();
      }
    } catch {
      // Keep the query param already in the URL if metadata is unavailable.
    }
    return state.version;
  }

  window.SiteVersion = state;
  window.loadSiteVersion = loadSiteVersion;
  window.versionedHref = versionedHref;
  window.syncVersionedLinks = syncVersionedLinks;
})();
