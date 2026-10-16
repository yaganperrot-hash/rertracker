/* ── Sélecteur de ligne + panneau « usager moyen » ────────────
   Composant partagé entre la home (/) et les pages par ligne (/:slug).
   Dépend de : LINE_META (global), formatDuree() (duree.js).
   Expose : window.Pick                                                */
(function () {
  'use strict';

  // ── Slug ↔ ID mapping (miroir de backend/config.py) ──
  const SLUGS = {};
  const SLUG_TO_ID = {};
  Object.entries(LINE_META).forEach(([id]) => {
    let slug;
    if (id.startsWith('RER_'))        slug = 'rer-' + id.slice(4).toLowerCase();
    else if (id.startsWith('TRANSILIEN_')) slug = 'ligne-' + id.slice(11).toLowerCase();
    else if (id === 'METRO_3B')       slug = 'metro-3bis';
    else if (id === 'METRO_7B')       slug = 'metro-7bis';
    else if (id.startsWith('METRO_')) slug = 'metro-' + id.slice(6).toLowerCase();
    else slug = id.toLowerCase();
    SLUGS[id] = slug;
    SLUG_TO_ID[slug] = id;
  });

  // ── Réseau de chaque ligne ──
  function reseau(id) {
    if (id.startsWith('RER_')) return 'rer';
    if (id.startsWith('TRANSILIEN_')) return 'transilien';
    return 'metro';
  }
  const NET_LABEL = { rer: 'RER', transilien: 'Transilien', metro: 'M\u00E9tro' };

  // ── Périodes calendaires, date de Paris : journée en cours, semaine depuis lundi, année depuis le 1er janvier ──
  const PERIOD_LABEL = { jour: "aujourd'hui", semaine: 'cette semaine', annee: 'cette ann\u00E9e' };

  // Journée comptée en cours : elle commence à l'heure de reprise des relevés (collecte_heure_debut, /api/reference)
  let heureDebutJournee = 6;
  function parisToday() {
    const [y, m, d] = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Paris' })
      .format(new Date(Date.now() - heureDebutJournee * 3600000)).split('-').map(Number);
    return { y, m, d };
  }

  // Nombre de jours à demander à l'API (période glissante qui se termine aujourd'hui)
  function periodDays(period) {
    const t = parisToday();
    const jour = Date.UTC(t.y, t.m - 1, t.d);
    if (period === 'semaine') return (new Date(jour).getUTCDay() + 6) % 7 + 1;
    if (period === 'annee') return Math.round((jour - Date.UTC(t.y, 0, 1)) / 86400000) + 1;
    return 1;
  }

  function fmtJourMois(iso) {
    const [, m, d] = iso.split('-');
    return d + '/' + m;
  }

  // Ce que couvrent les trois chiffres, écrit au-dessus d'eux
  function periodCaption(period, data) {
    let txt;
    if (period === 'semaine') txt = 'Cette semaine \u00B7 depuis le lundi ' + fmtJourMois(data.from);
    else if (period === 'annee') {
      var debut = (data.debut_donnees && data.debut_donnees > data.from) ? data.debut_donnees : data.from;
      txt = 'En ' + debut.slice(0, 4) + ' \u00B7 depuis le ' + fmtJourMois(debut);
    }
    else txt = 'Aujourd\u2019hui \u00B7 depuis ' + data.heure_debut_journee + ' h';
    return txt;
  }

  // Durée compacte de la carte : les jours s'écrivent « jrs » (« j » seul se lisait mal)
  function dureeCarte(min) {
    return formatDuree(min, true).replace(/(\d+) j(?![a-z])/g, function (_, n) {
      return n + (n === '1' ? ' jr' : ' jrs');
    });
  }

  // ── Cache des données (fréquentation + stats par ligne/période) ──
  let frequentation = null;
  let smicHoraire = 12.31;
  const statsCache = {};

  async function loadReference() {
    if (frequentation) return;
    try {
      const res = await fetch('/api/reference');
      if (!res.ok) return;
      const ref = await res.json();
      frequentation = ref.frequentation || {};
      smicHoraire = ref.smic_horaire || 12.31;
      if (ref.collecte_heure_debut != null) heureDebutJournee = ref.collecte_heure_debut;
    } catch (_) { frequentation = {}; }
  }

  async function loadLineStats(id, days) {
    const key = id + '_' + days;
    if (statsCache[key]) return statsCache[key];
    try {
      const res = await fetch('/api/stats/line/' + id + '?period=' + days);
      if (!res.ok) return null;
      const data = await res.json();
      statsCache[key] = data;
      return data;
    } catch (_) { return null; }
  }

  // ── Retard moyen pondéré (calculé par le backend) ──
  function perUser(data) {
    if (!data) return { minutes: 0, cout: 0 };
    return {
      minutes: data.retard_moyen_min || 0,
      cout: data.retard_moyen_eur || 0,
    };
  }

  // ── Formatage nombres FR ──
  function fmtEur(n) {
    if (n < 0.01) return '0,00';
    return n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function fmtMin(n) {
    return Math.round(n).toLocaleString('fr-FR');
  }

  // ── Classement de la ligne ──
  async function computeRank(lineId, days) {
    const promises = Object.keys(LINE_META).map(async id => {
      const data = await loadLineStats(id, days);
      return { id, cout: data ? (data.total_cout_eur || 0) : 0 };
    });
    const all = await Promise.all(promises);
    all.sort((a, b) => b.cout - a.cout);
    const idx = all.findIndex(x => x.id === lineId);
    return idx >= 0 ? idx + 1 : null;
  }

  // ── Construction du DOM ──
  function init(container, options) {
    const opts = Object.assign({
      showTitle: true,
      showPageLink: true,
      showRank: false,
      preselect: null,
      defaultTab: null,       // 'rer', 'transilien', 'metro'
      defaultPeriod: 'jour',
      onSelect: null,
    }, options);

    let currentLine = null;
    let currentPeriod = opts.defaultPeriod;
    let currentTab = opts.defaultTab || 'rer';

    // Grouper les lignes par réseau
    const groups = { rer: [], transilien: [], metro: [] };
    Object.entries(LINE_META).forEach(([id, meta]) => {
      groups[reseau(id)].push({ id, ...meta });
    });

    // HTML du sélecteur
    let html = '';
    if (opts.showTitle) {
      html += '<h2 class="pick-title">Et toi, ta ligne nous a fait perdre combien aujourd\u2019hui\u00A0?</h2>';
    }

    // Réseaux avec au moins une ligne
    const nets = ['rer', 'transilien', 'metro'].filter(n => groups[n].length > 0);
    if (!nets.includes(currentTab)) currentTab = nets[0] || 'rer';

    // Groupes par réseau : label + pastilles (tous visibles)
    nets.forEach(net => {
      html += '<div class="pick-group">';
      html += '<div class="pick-group-label">' + NET_LABEL[net] + '</div>';
      html += '<div class="pick-grid" data-net="' + net + '">';
      groups[net].forEach(l => {
        const tc = l.textColor ? ' data-tc="dark"' : '';
        html += '<div class="pick-dot" data-id="' + l.id + '" style="background:' + l.color + '"' + tc + '>' + l.short + '</div>';
      });
      html += '</div>';
      html += '</div>';
    });

    // Panneau
    html += '<div class="pick-panel" id="pick-panel">';
    html += '<div class="pick-panel-inner">';
    html += '  <button class="pp-close" id="pp-close" aria-label="Fermer"><svg viewBox="0 0 14 14"><line x1="1" y1="1" x2="13" y2="13"/><line x1="13" y1="1" x2="1" y2="13"/></svg></button>';
    html += '  <div class="pp-head">';
    html += '    <div class="pp-round" id="pp-round"></div>';
    html += '    <div class="pp-name" id="pp-name"></div>';
    html += '    <div class="pp-status" id="pp-status"></div>';
    html += '  </div>';
    html += '  <div class="pp-line-stats">';
    // Mêmes voyageurs, même période : le coût est le temps perdu valorisé au SMIC
    html += '    <div class="pp-period" id="pp-period"></div>';
    html += '    <div class="pp-stat"><span class="pp-stat-val" id="pp-stat-duree">\u2014</span><span class="pp-stat-label">Temps perdu par les voyageurs</span></div>';
    html += '    <div class="pp-stat"><span class="pp-stat-val" id="pp-stat-cout">\u2014</span><span class="pp-stat-label">ont \u00E9t\u00E9 perdus \u00E0 cause des perturbations</span></div>';
    html += '    <div class="pp-stat"><span class="pp-stat-val" id="pp-stat-incidents">\u2014</span><span class="pp-stat-label">Trains en retard ou supprim\u00E9s</span></div>';
    html += '  </div>';
    html += '  <div class="pp-toggle">';
    html += '    <button type="button" data-p="jour"' + (currentPeriod === 'jour' ? ' class="on"' : '') + '>Aujourd\u2019hui</button>';
    html += '    <button type="button" data-p="semaine"' + (currentPeriod === 'semaine' ? ' class="on"' : '') + '>Semaine</button>';
    html += '    <button type="button" data-p="annee"' + (currentPeriod === 'annee' ? ' class="on"' : '') + '>Ann\u00E9e</button>';
    html += '  </div>';
    if (opts.showRank) {
      html += '  <div class="pp-rank" id="pp-rank"></div>';
    }
    html += '  <div class="pp-actions">';
    html += '    <button type="button" class="pp-btn-share" id="pp-share">Partager</button>';
    if (opts.showPageLink) {
      html += '    <a id="pp-page-link" href="#">Page compl\u00E8te \u2192</a>';
    }
    html += '  </div>';
    html += '</div></div>';

    container.innerHTML = html;

    // Refs
    const panel = container.querySelector('#pick-panel');
    const ppRound = container.querySelector('#pp-round');
    const ppName = container.querySelector('#pp-name');
    const ppStatus = container.querySelector('#pp-status');
    const ppRank = container.querySelector('#pp-rank');
    const ppShare = container.querySelector('#pp-share');
    const ppPageLink = container.querySelector('#pp-page-link');
    const ppStatIncidents = container.querySelector('#pp-stat-incidents');
    const ppStatCout = container.querySelector('#pp-stat-cout');
    const ppStatDuree = container.querySelector('#pp-stat-duree');
    const ppPeriod = container.querySelector('#pp-period');

    // ── Onglets (rétro-compatibilité) ──
    function switchTab(net) { currentTab = net; }

    // ── Sélection d'une pastille ──
    async function select(lineId, scroll) {
      currentLine = lineId;
      const meta = LINE_META[lineId];
      if (!meta) return;

      // Surligner
      container.querySelectorAll('.pick-dot').forEach(d => d.classList.toggle('sel', d.dataset.id === lineId));

      // Aligner l'onglet sur le réseau de la ligne
      const net = reseau(lineId);
      if (net !== currentTab) switchTab(net);

      // Déplacer le panneau juste après le groupe de la ligne cliquée
      const dot = container.querySelector('.pick-dot[data-id="' + lineId + '"]');
      if (dot) {
        const group = dot.closest('.pick-group');
        if (group && group.nextElementSibling !== panel) {
          group.after(panel);
        }
      }

      // Mettre à jour l'en-tête du panneau
      ppRound.textContent = meta.short;
      ppRound.style.background = meta.color;
      if (meta.textColor) ppRound.setAttribute('data-tc', 'dark');
      else ppRound.removeAttribute('data-tc');
      ppName.textContent = meta.name;

      // Bouton partage couleur
      ppShare.style.background = meta.color;
      ppShare.style.color = meta.textColor || '#fff';

      // Lien page complète
      if (ppPageLink) ppPageLink.href = '/' + SLUGS[lineId];

      // Ouvrir le panneau
      panel.classList.add('open');

      // Charger et afficher les données
      await updatePanel();

      // Scroll
      if (scroll) panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

      // Persister
      try { localStorage.setItem('pick_line', lineId); } catch (_) {}
      if (opts.onSelect) opts.onSelect(lineId);
    }

    async function updatePanel() {
      if (!currentLine) return;
      await loadReference();
      const days = periodDays(currentPeriod);
      const data = await loadLineStats(currentLine, days);

      // Stats réseau de la ligne
      ppPeriod.textContent = data ? periodCaption(currentPeriod, data) : '';
      ppStatDuree.textContent = data ? dureeCarte(data.total_minutes_voyageurs || 0) : '\u2014';
      ppStatCout.textContent = data ? (data.total_cout_eur || 0).toLocaleString('fr-FR') + ' \u20AC' : '\u2014';
      ppStatIncidents.textContent = data ? (data.total_incidents || 0).toLocaleString('fr-FR') : '\u2014';

      // Statut : perturbé si incidents aujourd'hui
      const todayData = await loadLineStats(currentLine, 1);
      const hasIncidents = todayData && (todayData.total_incidents || 0) > 0;
      ppStatus.textContent = hasIncidents ? 'Perturb\u00E9' : 'OK';
      ppStatus.className = 'pp-status ' + (hasIncidents ? 'perturb\u00E9' : 'ok');

      // Classement
      if (ppRank && opts.showRank) {
        const rank = await computeRank(currentLine, days);
        if (rank) {
          const total = Object.keys(LINE_META).length;
          ppRank.innerHTML = '<strong>' + rank + (rank === 1 ? '\u02B3\u1D49' : '\u1D49') + ' pire ligne</strong> sur ' + total + ' \u00B7 ' + PERIOD_LABEL[currentPeriod];
        } else {
          ppRank.textContent = '';
        }
      }
    }

    // ── Fermer le panneau ──
    container.querySelector('#pp-close').addEventListener('click', function() {
      panel.classList.remove('open');
      container.querySelectorAll('.pick-dot').forEach(d => d.classList.remove('sel'));
      currentLine = null;
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    // ── Clic sur les pastilles ──
    container.querySelectorAll('.pick-dot').forEach(dot => {
      dot.addEventListener('click', () => {
        select(dot.dataset.id, true).catch(err => console.error('[Pick] select error:', err));
      });
    });

    // ── Toggle période ──
    container.querySelector('.pp-toggle').addEventListener('click', e => {
      const btn = e.target.closest('button[data-p]');
      if (!btn) return;
      container.querySelectorAll('.pp-toggle button').forEach(b => b.classList.remove('on'));
      btn.classList.add('on');
      currentPeriod = btn.dataset.p;
      updatePanel();
    });

    // ── Génération du canvas 1080×1080 ──
    function buildShareCanvas(meta, data) {
      const W = 1080, H = 1080;
      const canvas = document.createElement('canvas');
      canvas.width = W; canvas.height = H;
      const ctx = canvas.getContext('2d');

      ctx.fillStyle = '#F7F4EF';
      ctx.fillRect(0, 0, W, H);

      const cx = W / 2, cy = 280;
      ctx.beginPath();
      ctx.arc(cx, cy, 90, 0, Math.PI * 2);
      ctx.fillStyle = meta.color;
      ctx.fill();
      ctx.fillStyle = meta.textColor || '#fff';
      ctx.font = '900 60px Roboto, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(meta.short, cx, cy);

      ctx.fillStyle = '#000';
      ctx.font = '700 36px Roboto, sans-serif';
      ctx.fillText(meta.name, cx, cy + 140);

      ctx.fillStyle = '#000';
      ctx.font = '900 72px Roboto, sans-serif';
      ctx.fillText(data ? formatDuree(data.total_minutes_voyageurs || 0, true) : '\u2014', cx, cy + 260);

      ctx.fillStyle = '#555';
      ctx.font = '400 28px Roboto, sans-serif';
      ctx.fillText('de temps perdu par les voyageurs', cx, cy + 310);

      ctx.fillStyle = '#000';
      ctx.font = '700 36px Roboto, sans-serif';
      ctx.fillText((data ? (data.total_cout_eur || 0).toLocaleString('fr-FR') : '\u2014') + ' \u20AC au SMIC', cx, cy + 390);
      ctx.fillText((data ? (data.total_incidents || 0).toLocaleString('fr-FR') : '\u2014') + ' trains en retard ou supprim\u00E9s', cx, cy + 440);

      ctx.fillStyle = '#555';
      ctx.font = '500 26px Roboto, sans-serif';
      ctx.fillText(PERIOD_LABEL[currentPeriod], cx, cy + 500);

      ctx.fillStyle = 'rgba(0,0,0,0.12)';
      ctx.font = '500 22px Roboto, sans-serif';
      ctx.fillText('retards-idf.fr/' + SLUGS[currentLine], cx, H - 60);

      ctx.fillStyle = 'rgba(0,0,0,0.15)';
      ctx.font = '900 20px Roboto, sans-serif';
      ctx.fillText('RETARDS IDF', cx, H - 100);

      return canvas;
    }

    function shareText(meta, data) {
      // Mêmes mots que la carte : durée en « jrs », montant « perdu à cause des perturbations »
      var duree = data ? dureeCarte(data.total_minutes_voyageurs || 0) : '\u2014';
      var cout = data ? (data.total_cout_eur || 0).toLocaleString('fr-FR') : '\u2014';
      return meta.name + ', ' + PERIOD_LABEL[currentPeriod] + ' : ' + duree + ' et ' + cout +
        '\u00A0\u20AC ont \u00E9t\u00E9 perdus \u00E0 cause des perturbations.';
    }

    // Le fichier doit déjà exister : un téléchargement lancé après une attente (toBlob) ou après
    // l'ouverture d'un onglet n'est plus rattaché au clic, et le navigateur l'ignore.
    function downloadFile(file) {
      var url = URL.createObjectURL(file);
      var a = document.createElement('a');
      a.href = url;
      a.download = file.name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
    }

    // ── Menu de partage ──
    var shareMenu = null;

    function closeShareMenu() {
      if (shareMenu) { shareMenu.remove(); shareMenu = null; }
      document.removeEventListener('click', onDocClickShare, true);
    }
    function onDocClickShare(e) {
      if (shareMenu && !shareMenu.contains(e.target) && e.target !== ppShare) closeShareMenu();
    }

    ppShare.addEventListener('click', async function (e) {
      e.stopPropagation();
      if (!currentLine) return;
      if (shareMenu) { closeShareMenu(); return; }

      var meta = LINE_META[currentLine];
      var slug = SLUGS[currentLine];
      var days = periodDays(currentPeriod);
      await loadReference();
      var data = await loadLineStats(currentLine, days);

      // Image préparée dès l'ouverture du menu : le partage natif doit partir dans le clic lui-même
      // (Safari le refuse après une attente), donc le fichier doit déjà exister à ce moment-là.
      // toDataURL est synchrone — pas de race condition avec les clics du menu.
      var canvas = buildShareCanvas(meta, data);
      var dataUrl = canvas.toDataURL('image/png');
      var bin = atob(dataUrl.split(',')[1]);
      var buf = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
      var shareFile = new File([buf], 'retards-' + slug + '.png', { type: 'image/png' });

      shareMenu = document.createElement('div');
      shareMenu.className = 'pp-share-menu';
      shareMenu.innerHTML =
        '<button type="button" class="pp-share-item" data-action="x">' +
        '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>' +
        'Partager sur X</button>' +
        '<button type="button" class="pp-share-item" data-action="instagram">' +
        '<svg viewBox="0 0 24 24" width="18" height="18"><path fill-rule="evenodd" d="M7 2h10a5 5 0 0 1 5 5v10a5 5 0 0 1-5 5H7a5 5 0 0 1-5-5V7a5 5 0 0 1 5-5zm0 2a3 3 0 0 0-3 3v10a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3V7a3 3 0 0 0-3-3H7zm5 3.5a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9zm0 2a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM17.5 5.4a1.1 1.1 0 1 1 0 2.2 1.1 1.1 0 0 1 0-2.2z"/></svg>' +
        'Partager sur Instagram</button>';

      ppShare.parentElement.style.position = 'relative';
      ppShare.parentElement.appendChild(shareMenu);

      shareMenu.addEventListener('click', function (ev) {
        var btn = ev.target.closest('[data-action]');
        if (!btn) return;

        if (btn.dataset.action === 'x') {
          // X n'accepte qu'un texte et un lien depuis un site web : pas d'image jointe possible.
          // Lien ajouté seulement si le site a un nom de domaine : une adresse IP n'est pas cliquable sur X.
          var text = shareText(meta, data);
          if (!/^[\d.]+$|:/.test(window.location.hostname) && window.location.hostname !== 'localhost') {
            text += '\n\n' + window.location.origin + '/' + slug;
          }
          window.open('https://twitter.com/intent/tweet?text=' + encodeURIComponent(text), '_blank');
        } else if (btn.dataset.action === 'instagram') {
          // Instagram n'a pas de lien de partage web. Téléphone : menu de partage du système avec l'image.
          // Ordinateur : l'image est enregistrée et instagram.com s'ouvre pour la publier.
          if (!shareFile) return;
          if (navigator.canShare && navigator.canShare({ files: [shareFile] })) {
            navigator.share({ files: [shareFile] }).catch(function (err) {
              if (!err || err.name !== 'AbortError') downloadFile(shareFile);
            });
          } else {
            downloadFile(shareFile);
            window.open('https://www.instagram.com/', '_blank');
          }
        }
        closeShareMenu();
      });

      setTimeout(function () { document.addEventListener('click', onDocClickShare, true); }, 0);
    });

    // ── Pré-sélection ──
    if (opts.preselect) {
      select(opts.preselect, false);
    }

    return {
      select,
      getCurrentLine: () => currentLine,
      getSlug: id => SLUGS[id],
      getId: slug => SLUG_TO_ID[slug],
    };
  }

  window.Pick = { init, SLUGS, SLUG_TO_ID, perUser, loadReference, loadLineStats, fmtEur, fmtMin };
})();
