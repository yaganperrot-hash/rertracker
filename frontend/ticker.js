/* Bandeau défilant des incidents en cours — accueil et méthode.
   Source : /api/incidents/current ; aucun texte d'incident écrit en dur. */
(function () {
  // RER_A → « RER A » ; TRANSILIEN_H → « Transilien H »
  function nomLigne(id) {
    const [type, lettre = ''] = String(id).split('_');
    const nom = type === 'RER' ? type : type.charAt(0) + type.slice(1).toLowerCase();
    return `${nom} ${lettre}`.trim();
  }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  function render(incidents) {
    const el = document.getElementById('ticker-track');
    if (!el) return;
    if (!incidents.length) {
      el.textContent = 'Aucun incident en cours sur le réseau RER et Transilien';
      return;
    }
    const texte = incidents.slice(0, 8).map(inc => {
      const duree = inc.duree_minutes || 0;
      return `⚠ ${esc(nomLigne(inc.line_id))} — ${esc(inc.resume || inc.cause || inc.type_incident)}` +
        (duree > 0 ? ` — ${duree} min` : '');
    }).join('  &nbsp;•&nbsp;  ');
    el.innerHTML = texte + '  &nbsp;&nbsp;&nbsp;  ' + texte;
  }

  async function charger() {
    try {
      const r = await fetch('/api/incidents/current');
      if (r.ok) render(await r.json());
    } catch (_) { /* on garde le texte précédent */ }
  }

  window.Ticker = { render, charger };
})();
