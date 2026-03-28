(function () {
  const state = {
    version: new URLSearchParams(window.location.search).get('v') || '',
  };

  function setUrlVersion(version) {
    if (!version) return;
    const url = new URL(window.location.href);
    if (url.searchParams.get('v') === version) return;
    url.searchParams.set('v', version);
    window.history.replaceState({}, '', url.toString());
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
      const res = await fetch('./data/site_meta.json', { cache: 'no-store' });
      if (!res.ok) return state.version;
      const meta = await res.json();
      const version = meta.version || meta.build_version || '';
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
