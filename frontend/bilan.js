/* ── Bilans /statistiques et /annee : lignes, formats, classement ──
   Les chiffres viennent des JSON générés par backend/bilans.py ;
   aucun calcul de coût ici. Deux unités à l'écran : € et minutes. */
(function () {
  function L(nom, lbl, fond, texte, encre) {
    return { nom, lbl, fond, texte: texte || '#fff', encre: encre || fond };
  }

  // Couleurs de l'accueil (index.html, LINE_META) — pas celles des maquettes.
  // encre : variante lisible sur fond blanc pour les jaunes.
  const LIGNES = {
    RER_A: L('RER A', 'RER A', '#E2231A'),
    RER_B: L('RER B', 'RER B', '#5191CF'),
    RER_C: L('RER C', 'RER C', '#C8A800', '#1a1a17', '#8A7400'),
    RER_D: L('RER D', 'RER D', '#00814F'),
    RER_E: L('RER E', 'RER E', '#B04191'),
    TRANSILIEN_H: L('Transilien H', 'H', '#7B7B7B'),
    TRANSILIEN_J: L('Transilien J', 'J', '#D2B464', '#1a1a17', '#8F7431'),
    TRANSILIEN_K: L('Transilien K', 'K', '#8C4B31'),
    TRANSILIEN_L: L('Transilien L', 'L', '#9F3E96'),
    TRANSILIEN_N: L('Transilien N', 'N', '#333333'),
    TRANSILIEN_P: L('Transilien P', 'P', '#E87722'),
    TRANSILIEN_R: L('Transilien R', 'R', '#228B22'),
    TRANSILIEN_U: L('Transilien U', 'U', '#7B0F1F'),
    // Métro
    METRO_1:  L('Métro 1',    'M1',  '#FFBE00', '#000', '#C89600'),
    METRO_2:  L('Métro 2',    'M2',  '#003CA6'),
    METRO_3:  L('Métro 3',    'M3',  '#837902'),
    METRO_3B: L('Métro 3bis', 'M3b', '#6EC4E8', '#000', '#3A9AC0'),
    METRO_4:  L('Métro 4',    'M4',  '#CF009E'),
    METRO_5:  L('Métro 5',    'M5',  '#FF7E2E', '#000', '#C05A18'),
    METRO_6:  L('Métro 6',    'M6',  '#6ECA97', '#000', '#3A9668'),
    METRO_7:  L('Métro 7',    'M7',  '#FA9ABA', '#000', '#C06A8A'),
    METRO_7B: L('Métro 7bis', 'M7b', '#6ECA97', '#000', '#3A9668'),
    METRO_8:  L('Métro 8',    'M8',  '#E19BDF', '#000', '#A060A0'),
    METRO_9:  L('Métro 9',    'M9',  '#B6BD00', '#000', '#888C00'),
    METRO_10: L('Métro 10',   'M10', '#C9910D', '#000', '#966C0A'),
    METRO_11: L('Métro 11',   'M11', '#704B1C'),
    METRO_12: L('Métro 12',   'M12', '#007852'),
    METRO_13: L('Métro 13',   'M13', '#6EC4E8', '#000', '#3A9AC0'),
    METRO_14: L('Métro 14',   'M14', '#62259D'),
  };

  const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin',
                'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
  const MOIS_COURT = ['jan', 'fév', 'mar', 'avr', 'mai', 'jun', 'jul', 'aoû', 'sep', 'oct', 'nov', 'déc'];
  const MOIS_ABREV = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin',
                      'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];

  const NBSP = ' ';
  const FINE = ' ';

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function cap(s) { return s ? s[0].toUpperCase() + s.slice(1) : s; }

  function fmtNombre(n) { return Number(n || 0).toLocaleString('fr-FR'); }
  function fmtDecimal1(v) { return v.toLocaleString('fr-FR', { maximumFractionDigits: 1 }); }
  function fmtEuros(n) { return fmtNombre(n) + NBSP + '€'; }

  function fmtEurosCompact(n) {
    n = n || 0;
    if (n >= 1e6) return fmtDecimal1(n / 1e6) + NBSP + 'M€';
    if (n >= 1e4) return fmtNombre(Math.round(n / 1e3)) + NBSP + 'k€';
    return fmtEuros(n);
  }

  // Au-delà de 100 000, arrondi au millier ; au-delà de 10 millions, « 35,4 M »
  function fmtMinutes(n) {
    n = n || 0;
    if (n >= 1e7) return { valeur: fmtDecimal1(n / 1e6) + NBSP + 'M', suffixe: 'de minutes perdues' };
    const v = n >= 1e5 ? Math.round(n / 1e3) * 1e3 : n;
    return { valeur: fmtNombre(v), suffixe: n <= 1 ? 'minute perdue' : 'minutes perdues' };
  }

  function fmtIncidents(n) {
    return `${fmtNombre(n)} incident${n > 1 ? 's' : ''}`;
  }

  function fmtDelta(pct) {
    if (pct === null || pct === undefined) return { texte: 'n.d.', classe: 'nd' };
    if (Math.abs(pct) < 0.5) return { texte: '=' + NBSP + '0' + FINE + '%', classe: 'nd' };
    const v = fmtNombre(Math.round(Math.abs(pct))) + FINE + '%';
    return pct > 0 ? { texte: '▲' + NBSP + v, classe: 'hausse' } : { texte: '▼' + NBSP + v, classe: 'baisse' };
  }

  // « −31 % » (signe moins typographique)
  function fmtPctSigne(pct) {
    const v = fmtNombre(Math.round(Math.abs(pct))) + FINE + '%';
    return (pct < 0 ? '−' : '+') + v;
  }

  function fmtHeure(iso) {
    return new Date(iso)
      .toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Paris' })
      .replace(':', ' h ');
  }

  function fmtDate(iso) {
    const [, m, j] = String(iso).split('-');
    return `${j}/${m}`;
  }

  function badge(id) {
    const l = LIGNES[id];
    return l ? `<span class="badge" style="background:${l.fond};color:${l.texte}">${esc(l.lbl)}</span>` : '';
  }

  async function chargerJSON(url) {
    const r = await fetch(url);
    if (r.status === 404) return null;
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }

  function pied(meta) {
    const smic = meta.smic_horaire.toLocaleString('fr-FR', { minimumFractionDigits: 2 });
    const recalcul = meta.recalcul_minutes ? ` · recalcul toutes les ${meta.recalcul_minutes} min` : '';
    return `Données API PRIM · IDF Mobilités · mis à jour à ${fmtHeure(meta.genere_a)}` +
      `${recalcul} · base SMIC brut ${smic}${NBSP}€/h`;
  }

  function rangee(l, maxMin) {
    const m = LIGNES[l.id];
    const largeur = l.minutes > 0 ? Math.max(2, l.minutes / maxMin * 100) : 0;
    const titre = `${m.nom} — ${fmtNombre(l.minutes)} minutes perdues · ${fmtIncidents(l.incidents)}`;
    return `<div class="row" title="${esc(titre)}">` +
      `<span class="lbl" style="background:${m.fond};color:${m.texte}">${esc(m.lbl)}</span>` +
      `<div class="track"><div class="fill" style="width:${largeur.toFixed(1)}%;background:${m.fond}"></div></div>` +
      `<span class="val">${esc(fmtEuros(l.cout_eur))}</span></div>`;
  }

  // Lignes déjà triées par le backend ; celles sans temps perdu repliées sous « voir tout »
  function renderClassement(el, lignes) {
    const connues = (lignes || []).filter(l => LIGNES[l.id]);
    const actives = connues.filter(l => l.minutes > 0);
    const zeros = connues.filter(l => !(l.minutes > 0));
    const maxMin = actives.length ? Math.max(...actives.map(l => l.minutes)) : 1;

    let html = actives.length
      ? actives.map(l => rangee(l, maxMin)).join('')
      : '<p class="vide">Aucune minute perdue sur la période.</p>';
    if (zeros.length) {
      html += `<div class="plie" hidden>${zeros.map(l => rangee(l, maxMin)).join('')}</div>` +
        `<div class="repli">+ ${zeros.length} ligne${zeros.length > 1 ? 's' : ''} sans temps perdu · ` +
        `<button type="button" aria-expanded="false">voir tout</button></div>`;
    }
    el.innerHTML = html;

    const bouton = el.querySelector('.repli button');
    if (bouton) {
      bouton.addEventListener('click', () => {
        const plie = el.querySelector('.plie');
        plie.hidden = !plie.hidden;
        bouton.textContent = plie.hidden ? 'voir tout' : 'masquer';
        bouton.setAttribute('aria-expanded', String(!plie.hidden));
      });
    }
  }

  window.Bilan = {
    LIGNES, MOIS, MOIS_COURT, MOIS_ABREV,
    esc, cap, fmtNombre, fmtEuros, fmtEurosCompact, fmtMinutes, fmtIncidents,
    fmtDelta, fmtPctSigne, fmtHeure, fmtDate, badge, chargerJSON, pied, renderClassement,
  };
})();
