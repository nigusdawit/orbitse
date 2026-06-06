/* admin/gx-table.js — task 093, gap §0.5. Opt-in row-action + bulk-select enhancer.
   ANY admin table adopts it with ZERO per-tab JS:

     <table class="gx-table" data-gx-actions="delete:Delete,export:Export">
       <thead><tr><th>Name</th>…</tr></thead>
       <tbody><tr data-gx-id="42"><td>…</td>…</tr>…</tbody>
     </table>

   It adds a leading select-all + per-row checkbox column and a sticky bulk-action bar
   (selection count + the buttons from data-gx-actions + Clear) shown only when ≥1 row
   is checked. Clicking an action fires CustomEvent('gx:bulk', {detail:{action, ids,
   table}}) that the owning tab listens for (the per-row routes already exist).

   DECLARATIVE + IDEMPOTENT (safe to call again after a re-render) + a NO-OP on tables
   that don't opt in. The OPT-IN TRIGGER is the `data-gx-actions` attribute (the
   `gx-table` CLASS alone is also a pre-existing styling class, so we must NOT enhance
   on the class). Auto-enhances every `table[data-gx-actions]` on load; call
   window.gxTable.enhance(tableEl) after you re-render a table's rows. Never throws. */
(function () {
  'use strict';
  var doc = document;

  function _parseActions(s) {
    // "delete:Delete,export:Export" -> [{action:'delete',label:'Delete'}, …]
    return (s || '').split(',').map(function (p) {
      var bits = p.split(':'); var a = (bits[0] || '').trim();
      return a ? { action: a, label: (bits[1] || a).trim() } : null;
    }).filter(Boolean);
  }
  function _rows(t) { return Array.prototype.slice.call(t.querySelectorAll('tbody tr[data-gx-id]')); }
  function _checked(t) { return _rows(t).filter(function (r) { var c = r.querySelector('.gx-check'); return c && c.checked; }); }
  function _ids(rows) { return rows.map(function (r) { return r.getAttribute('data-gx-id'); }); }

  function _sync(t) {
    var bar = t.__gxBar; if (!bar) return;
    var n = _checked(t).length, total = _rows(t).length;
    var cnt = bar.querySelector('.gx-bulk-count'); if (cnt) cnt.textContent = n + ' selected';
    bar.hidden = (n === 0);
    var all = t.querySelector('.gx-check-all');
    if (all) { all.checked = (n > 0 && n === total); all.indeterminate = (n > 0 && n < total); }
  }

  function enhance(t) {
    try {
      if (!t || !t.querySelector) return;
      // TRUE opt-in: leave styling-only gx-tables (no actions, no gx-id rows) untouched.
      if (!t.getAttribute('data-gx-actions') && !t.querySelector('tbody tr[data-gx-id]')) return;
      if (t.getAttribute('data-gx-on') === '1') { _addRowChecks(t); _sync(t); return; }  // re-render: just (re)wire new rows
      t.setAttribute('data-gx-on', '1');
      var actions = _parseActions(t.getAttribute('data-gx-actions'));

      // header select-all
      var htr = t.querySelector('thead tr');
      if (htr && !htr.querySelector('.gx-check-th')) {
        var th = doc.createElement('th'); th.className = 'gx-check-th';
        var all = doc.createElement('input'); all.type = 'checkbox'; all.className = 'gx-check-all'; all.setAttribute('aria-label', 'Select all rows');
        all.addEventListener('change', function () { _rows(t).forEach(function (r) { var c = r.querySelector('.gx-check'); if (c) c.checked = all.checked; }); _sync(t); });
        th.appendChild(all); htr.insertBefore(th, htr.firstChild);
      }
      _addRowChecks(t);

      // one bulk bar per table, inserted right after it
      var bar = doc.createElement('div'); bar.className = 'gx-bulkbar'; bar.hidden = true;
      var cnt = doc.createElement('span'); cnt.className = 'gx-bulk-count'; bar.appendChild(cnt);
      actions.forEach(function (a) {
        var b = doc.createElement('button'); b.type = 'button'; b.className = 'gx-bulk-btn'; b.textContent = a.label;
        b.addEventListener('click', function () {
          var ids = _ids(_checked(t)); if (!ids.length) return;
          t.dispatchEvent(new CustomEvent('gx:bulk', { bubbles: true, detail: { action: a.action, ids: ids, table: t } }));
        });
        bar.appendChild(b);
      });
      var clear = doc.createElement('button'); clear.type = 'button'; clear.className = 'gx-bulk-clear'; clear.textContent = 'Clear';
      clear.addEventListener('click', function () {
        _rows(t).forEach(function (r) { var c = r.querySelector('.gx-check'); if (c) c.checked = false; });
        var a = t.querySelector('.gx-check-all'); if (a) { a.checked = false; a.indeterminate = false; } _sync(t);
      });
      bar.appendChild(clear);
      if (t.parentNode) t.parentNode.insertBefore(bar, t.nextSibling);
      t.__gxBar = bar;
      _sync(t);
    } catch (e) { if (window.console && console.warn) console.warn('[gx-table] enhance failed:', e); }
  }

  function _addRowChecks(t) {
    _rows(t).forEach(function (r) {
      if (r.querySelector('.gx-check')) return;
      var td = doc.createElement('td'); td.className = 'gx-check-td';
      var cb = doc.createElement('input'); cb.type = 'checkbox'; cb.className = 'gx-check'; cb.setAttribute('aria-label', 'Select row');
      cb.addEventListener('change', function () { _sync(t); });
      td.appendChild(cb); r.insertBefore(td, r.firstChild);
    });
  }

  function enhanceAll(root) {
    // Only tables that explicitly opted in (data-gx-actions) — NOT the styling class.
    try { Array.prototype.slice.call((root || doc).querySelectorAll('table[data-gx-actions]')).forEach(enhance); } catch (e) {}
  }

  window.gxTable = { enhance: enhance, enhanceAll: enhanceAll, sync: _sync };
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', function () { enhanceAll(); });
  else enhanceAll();
})();
