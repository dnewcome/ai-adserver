(function () {
  'use strict';

  // Locate our own script tag to read data attributes
  var scripts = document.querySelectorAll('script[data-zone]');
  var me = scripts[scripts.length - 1];
  if (!me) return;

  var zoneId   = me.dataset.zone;
  var zoneType = me.dataset.type || 'banner';   // banner | native
  var baseUrl  = me.dataset.base || 'http://localhost:8000';
  var containerId = 'aias-' + zoneId;
  var container = document.getElementById(containerId);
  if (!container) return;

  var pageUrl = encodeURIComponent(window.location.href);
  var endpoint = baseUrl + '/serve/' + zoneId + '?url=' + pageUrl;

  // ─── Renderers ────────────────────────────────────────────────────────────

  function renderBanner(data, el) {
    var c = data.creative;
    el.innerHTML = [
      '<a href="' + data.click_url + '" target="_blank" rel="noopener"',
      '   style="display:block;text-decoration:none;font-family:sans-serif;',
      '          background:#0f172a;color:#fff;border-radius:6px;overflow:hidden;',
      '          padding:14px 20px;box-sizing:border-box;position:relative;',
      '          border:1px solid #1e293b;">',
      '  <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;',
      '              color:#94a3b8;margin-bottom:4px;">Sponsored</div>',
      '  <div style="font-size:17px;font-weight:700;line-height:1.3;color:#f1f5f9;',
      '              margin-bottom:6px;">' + _esc(c.headline_long || c.headline_short) + '</div>',
      '  <div style="font-size:13px;color:#94a3b8;margin-bottom:12px;">' + _esc(c.body_copy) + '</div>',
      '  <span style="display:inline-block;background:#3b82f6;color:#fff;',
      '               font-size:12px;font-weight:600;padding:6px 14px;',
      '               border-radius:4px;letter-spacing:.03em;">' + _esc(c.cta) + '</span>',
      '  <div style="position:absolute;top:14px;right:16px;font-size:10px;',
      '              color:#475569;">' + _esc(data.brand_name || '') + '</div>',
      '</a>'
    ].join('');
  }

  function renderNative(data, el) {
    var c = data.creative;
    el.innerHTML = [
      '<a href="' + data.click_url + '" target="_blank" rel="noopener"',
      '   style="display:flex;gap:12px;text-decoration:none;font-family:sans-serif;',
      '          padding:12px;border:1px solid #e2e8f0;border-radius:6px;',
      '          background:#fff;align-items:flex-start;">',
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

  // ─── Fetch & render ────────────────────────────────────────────────────────

  function _esc(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  var xhr = new XMLHttpRequest();
  xhr.open('GET', endpoint, true);
  xhr.onreadystatechange = function () {
    if (xhr.readyState !== 4) return;
    if (xhr.status === 204 || !xhr.responseText) return; // no fill — stay blank
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
})();
