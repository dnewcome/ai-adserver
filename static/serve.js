(function () {
  'use strict';

  var BASE_URL = '';

  // ─── Queue processor ────────────────────────────────────────────────────────
  // Publishers call window._aias.push({zone, type, base}) per slot.
  // This script processes whatever is already in the queue, then installs
  // a live push() so late-arriving calls are handled immediately.

  // ─── Visitor ID cookie (#13 frequency capping) ──────────────────────────
  function _getOrCreateVisitorId() {
    var name = '_aias_vid=';
    var cookies = document.cookie.split(';');
    for (var i = 0; i < cookies.length; i++) {
      var c = cookies[i].trim();
      if (c.indexOf(name) === 0) return c.substring(name.length);
    }
    // Generate a random visitor ID and persist for 365 days
    var vid = 'v' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    var expires = new Date(Date.now() + 365 * 86400 * 1000).toUTCString();
    document.cookie = '_aias_vid=' + vid + '; expires=' + expires + '; path=/; SameSite=Lax';
    return vid;
  }

  var VISITOR_ID = _getOrCreateVisitorId();

  function processSlot(cfg) {
    var zoneId   = cfg.zone;
    var zoneType = cfg.type || 'banner';
    var baseUrl  = cfg.base || BASE_URL || window.location.origin;
    var containerId = cfg.containerId || ('aias-' + zoneId);
    var container   = document.getElementById(containerId);
    if (!container) return;

    var pageUrl  = encodeURIComponent(window.location.href);
    var endpoint = baseUrl + '/serve/' + zoneId + '?url=' + pageUrl + '&visitor_id=' + encodeURIComponent(VISITOR_ID);

    var xhr = new XMLHttpRequest();
    xhr.open('GET', endpoint, true);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status === 204 || !xhr.responseText) return;
      if (xhr.status !== 200) return;
      var data;
      try { data = JSON.parse(xhr.responseText); } catch (e) { return; }
      if (zoneType === 'native') {
        renderNative(data, container);
      } else {
        renderBanner(data, container);
      }
    };
    xhr.send();
  }

  // ─── Renderers ────────────────────────────────────────────────────────────

  function renderBanner(data, el) {
    var c = data.creative;
    var imgHtml = c.image_url
      ? '<img src="' + _esc(c.image_url) + '" alt="" style="width:100%;display:block;border-radius:4px 4px 0 0;max-height:180px;object-fit:cover;">'
      : '';
    el.innerHTML = [
      '<a href="' + data.click_url + '" target="_blank" rel="noopener"',
      '   style="display:block;text-decoration:none;font-family:sans-serif;',
      '          background:#0f172a;color:#fff;border-radius:6px;overflow:hidden;',
      '          box-sizing:border-box;position:relative;border:1px solid #1e293b;">',
      imgHtml,
      '  <div style="padding:14px 20px;">',
      '    <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;',
      '                color:#94a3b8;margin-bottom:4px;">Sponsored · ' + _esc(data.brand_name || '') + '</div>',
      '    <div style="font-size:17px;font-weight:700;line-height:1.3;color:#f1f5f9;',
      '                margin-bottom:6px;">' + _esc(c.headline_long || c.headline_short) + '</div>',
      '    <div style="font-size:13px;color:#94a3b8;margin-bottom:12px;">' + _esc(c.body_copy) + '</div>',
      '    <span style="display:inline-block;background:#3b82f6;color:#fff;',
      '                 font-size:12px;font-weight:600;padding:6px 14px;',
      '                 border-radius:4px;letter-spacing:.03em;">' + _esc(c.cta) + '</span>',
      '  </div>',
      '</a>'
    ].join('');
  }

  function renderNative(data, el) {
    var c = data.creative;
    var imgHtml = c.image_url
      ? '<img src="' + _esc(c.image_url) + '" alt="" style="width:72px;height:72px;object-fit:cover;border-radius:4px;flex-shrink:0;">'
      : '';
    el.innerHTML = [
      '<a href="' + data.click_url + '" target="_blank" rel="noopener"',
      '   style="display:flex;gap:12px;text-decoration:none;font-family:sans-serif;',
      '          padding:12px;border:1px solid #e2e8f0;border-radius:6px;',
      '          background:#fff;align-items:flex-start;">',
      imgHtml,
      '  <div style="flex:1;min-width:0;">',
      '    <div style="font-size:10px;letter-spacing:.07em;text-transform:uppercase;',
      '                color:#94a3b8;margin-bottom:3px;">Sponsored · ' + _esc(data.brand_name || '') + '</div>',
      '    <div style="font-size:15px;font-weight:600;color:#0f172a;line-height:1.35;',
      '                margin-bottom:4px;">' + _esc(c.headline_short) + '</div>',
      '    <div style="font-size:13px;color:#64748b;margin-bottom:10px;',
      '                white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + _esc(c.body_copy) + '</div>',
      '    <span style="font-size:12px;font-weight:600;color:#3b82f6;">' + _esc(c.cta) + ' →</span>',
      '  </div>',
      '</a>'
    ].join('');
  }

  function _esc(str) {
    return String(str || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ─── Bootstrap ───────────────────────────────────────────────────────────
  // Process any slots pushed before this script loaded, then take over push().

  var existing = window._aias && window._aias.q ? window._aias.q : [];
  existing.forEach(processSlot);

  window._aias = {
    push: processSlot,
    q: []
  };

})();
