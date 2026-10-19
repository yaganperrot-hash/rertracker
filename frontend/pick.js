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

    // Panneau (design carte : bande couleur, pastille ronde, accroche, montant, filet, SMIC, classement, signature)
    html += '<div class="pick-panel" id="pick-panel">';
    html += '<div class="pp-band" id="pp-band"></div>';
    html += '<div class="pick-panel-inner">';
    html += '  <button class="pp-close" id="pp-close" aria-label="Fermer"><svg viewBox="0 0 14 14"><line x1="1" y1="1" x2="13" y2="13"/><line x1="13" y1="1" x2="1" y2="13"/></svg></button>';
    html += '  <div class="pp-card-center">';
    html += '    <div class="pp-round" id="pp-round"></div>';
    html += '    <div class="pp-date" id="pp-date"></div>';
    html += '    <div class="pp-accroche" id="pp-accroche"></div>';
    html += '    <div class="pp-montant" id="pp-montant">\u2014</div>';
    html += '    <div class="pp-filet"></div>';
    html += '    <div class="pp-smic" id="pp-smic"></div>';
    html += '    <div class="pp-rank" id="pp-rank"></div>';
    html += '  </div>';
    html += '  <div class="pp-signature">RETARDS IDF \u00B7 retards-idf.fr</div>';
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
    const ppBand = container.querySelector('#pp-band');
    const ppRound = container.querySelector('#pp-round');
    const ppDate = container.querySelector('#pp-date');
    const ppAccroche = container.querySelector('#pp-accroche');
    const ppMontant = container.querySelector('#pp-montant');
    const ppSmic = container.querySelector('#pp-smic');
    const ppRank = container.querySelector('#pp-rank');
    const ppShare = container.querySelector('#pp-share');
    const ppPageLink = container.querySelector('#pp-page-link');

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

      // Mettre à jour le panneau carte
      ppBand.style.background = meta.color;
      ppRound.textContent = meta.short;
      ppRound.style.background = meta.color;
      if (meta.textColor) ppRound.setAttribute('data-tc', 'dark');
      else ppRound.removeAttribute('data-tc');

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
      const meta = LINE_META[currentLine];
      const days = periodDays(currentPeriod);
      const data = await loadLineStats(currentLine, days);

      // Date
      var dateStr = new Date().toLocaleDateString('fr-FR',
        { weekday: 'long', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Europe/Paris' });
      ppDate.textContent = dateStr.toUpperCase();

      var cout = data ? (data.total_cout_eur || 0) : 0;

      if (cout === 0) {
        var article = meta.name.startsWith('RER') ? 'le ' : 'la ';
        ppAccroche.textContent = 'Aucun retard sur ' + article + meta.name;
        ppMontant.textContent = "pour l'instant.";
        ppMontant.classList.add('pp-montant-zero');
        ppSmic.textContent = '';
      } else {
        var article = meta.name.startsWith('RER') ? 'le ' : 'la ';
        ppAccroche.textContent = "Aujourd'hui, " + article + meta.name + ' nous a co\u00FBt\u00E9';
        ppMontant.textContent = cout.toLocaleString('fr-FR') + ' \u20AC';
        ppMontant.classList.remove('pp-montant-zero');

        // Jours SMIC
        var jours = Math.floor(cout / (smicHoraire * 7));
        if (jours > 0) {
          var joursLabel;
          if (jours < 365) joursLabel = jours.toLocaleString('fr-FR') + ' jours';
          else {
            var mois = Math.round(jours / 30.44);
            if (mois < 24) joursLabel = mois + ' mois';
            else {
              var a = Math.floor(jours / 365.25);
              var m = Math.round((jours / 365.25 - a) * 12);
              joursLabel = a + ' ans' + (m ? ' ' + m + ' mois' : '');
            }
          }
          ppSmic.textContent = 'soit ' + joursLabel + ' de travail au SMIC';
        } else {
          ppSmic.textContent = '';
        }
      }

      // Classement
      const rank = await computeRank(currentLine, days);
      if (rank) {
        const total = Object.keys(LINE_META).length;
        var suf = rank === 1 ? '\u02B3\u1D49' : '\u1D49';
        ppRank.textContent = rank + suf + ' pire ligne / ' + total;
      } else {
        ppRank.textContent = '';
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

    // ── Génération du canvas 1080×1080 (nouvelle DA) ──
    function buildShareCanvas(meta, data) {
      var W = 1080, H = 1080;
      var canvas = document.createElement('canvas');
      canvas.width = W; canvas.height = H;
      var ctx = canvas.getContext('2d');

      var BG = '#F7F4EF', INK = '#000', SUB = '#333', MUTED = '#555', RED = '#C0392B';
      var PAD = 72;

      ctx.fillStyle = BG;
      ctx.fillRect(0, 0, W, H);
      ctx.textBaseline = 'alphabetic';

      // Bande couleur en haut (100px)
      ctx.fillStyle = meta.color;
      ctx.fillRect(0, 0, W, 100);

      // Pastille ronde (grosse)
      var cx = W / 2, circleY = 220, circleR = 68;
      ctx.beginPath();
      ctx.arc(cx, circleY, circleR, 0, Math.PI * 2);
      ctx.fillStyle = meta.color;
      ctx.fill();
      ctx.fillStyle = meta.textColor || '#fff';
      ctx.font = '900 60px Roboto, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(meta.short, cx, circleY);
      ctx.textBaseline = 'alphabetic';

      // Date en petites capitales
      var dateStr = new Date().toLocaleDateString('fr-FR',
        { weekday: 'long', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Europe/Paris' });
      dateStr = dateStr.toUpperCase();
      ctx.fillStyle = MUTED;
      ctx.font = '700 26px Roboto, sans-serif';
      ctx.fillText(dateStr, cx, 330);

      var cout = data ? (data.total_cout_eur || 0) : 0;
      if (cout === 0) {
        // Cas 0 €
        ctx.fillStyle = INK;
        ctx.font = '700 44px Roboto, sans-serif';
        ctx.fillText('Aucun retard sur', cx, 480);
        var article = meta.name.startsWith('RER') ? 'le ' : 'la ';
        ctx.fillText(article + meta.name, cx, 540);
        ctx.fillStyle = MUTED;
        ctx.font = '400 34px Roboto, sans-serif';
        ctx.fillText("pour l'instant.", cx, 620);
      } else {
        // Accroche
        var article = meta.name.startsWith('RER') ? 'le ' : 'la ';
        ctx.fillStyle = SUB;
        ctx.font = '400 36px Roboto, sans-serif';
        ctx.fillText("Aujourd'hui, " + article + meta.name + ' nous a co\u00FBt\u00E9', cx, 400);

        // Montant auto-sized (départ 140px)
        var coutTxt = cout.toLocaleString('fr-FR') + ' \u20AC';
        var fontSize = 140;
        ctx.font = '900 ' + fontSize + 'px Roboto, sans-serif';
        while (ctx.measureText(coutTxt).width > W - PAD * 2 && fontSize > 70) {
          fontSize -= 4;
          ctx.font = '900 ' + fontSize + 'px Roboto, sans-serif';
        }
        ctx.fillStyle = INK;
        ctx.fillText(coutTxt, cx, 540);

        // Filet
        ctx.beginPath();
        ctx.moveTo(PAD + 80, 600);
        ctx.lineTo(W - PAD - 80, 600);
        ctx.strokeStyle = MUTED;
        ctx.lineWidth = 2;
        ctx.stroke();

        // Jours SMIC en rouge
        var jours = Math.floor(cout / (smicHoraire * 7));
        if (jours > 0) {
          var joursLabel;
          if (jours < 365) joursLabel = jours.toLocaleString('fr-FR') + ' jours';
          else {
            var mois = Math.round(jours / 30.44);
            if (mois < 24) joursLabel = mois + ' mois';
            else {
              var a = Math.floor(jours / 365.25);
              var m = Math.round((jours / 365.25 - a) * 12);
              joursLabel = a + ' ans' + (m ? ' ' + m + ' mois' : '');
            }
          }
          ctx.fillStyle = RED;
          ctx.font = '700 36px Roboto, sans-serif';
          ctx.fillText('soit ' + joursLabel + ' de travail au SMIC', cx, 670);
        }

        // Classement
        if (data._rank) {
          var total = Object.keys(LINE_META).length;
          var suf = data._rank === 1 ? '\u02B3\u1D49' : '\u1D49';
          ctx.fillStyle = MUTED;
          ctx.font = '400 30px Roboto, sans-serif';
          ctx.fillText(data._rank + suf + ' pire ligne / ' + total, cx, 740);
        }
      }

      // « Partager » (bouton visuel centré)
      var btnW = 260, btnH = 64, btnR = 14;
      var btnX = cx - btnW / 2, btnY = H - 200;
      ctx.beginPath();
      ctx.roundRect(btnX, btnY, btnW, btnH, btnR);
      ctx.fillStyle = meta.color;
      ctx.fill();
      ctx.fillStyle = meta.textColor || '#fff';
      ctx.font = '700 28px Roboto, sans-serif';
      ctx.textBaseline = 'middle';
      ctx.fillText('Partager', cx, btnY + btnH / 2);
      ctx.textBaseline = 'alphabetic';

      // Footer
      var footY = H - 70;
      ctx.beginPath();
      ctx.moveTo(PAD, footY - 20);
      ctx.lineTo(W - PAD, footY - 20);
      ctx.strokeStyle = MUTED; ctx.lineWidth = 1;
      ctx.stroke();

      ctx.fillStyle = MUTED;
      ctx.font = '700 22px Roboto, sans-serif';
      ctx.fillText('RETARDS IDF \u00B7 retards-idf.fr', cx, footY + 8);

      return canvas;
    }

    function shareText(meta, data) {
      var cout = data ? (data.total_cout_eur || 0) : 0;
      var coutTxt = cout.toLocaleString('fr-FR');
      var article = meta.name.startsWith('RER') ? 'le ' : 'la ';

      // Jours SMIC
      var jours = Math.floor(cout / (smicHoraire * 7));
      var joursLabel = '';
      if (jours > 0) {
        if (jours < 365) joursLabel = jours.toLocaleString('fr-FR') + ' jours';
        else {
          var mois = Math.round(jours / 30.44);
          if (mois < 24) joursLabel = mois + ' mois';
          else {
            var a = Math.floor(jours / 365.25);
            var m = Math.round((jours / 365.25 - a) * 12);
            joursLabel = a + ' ans' + (m ? ' ' + m + ' mois' : '');
          }
        }
      }

      // Classement
      var rankTxt = '';
      if (data._rank) {
        var total = Object.keys(LINE_META).length;
        var suf = data._rank === 1 ? '\u02B3\u1D49' : '\u1D49';
        rankTxt = '\n' + data._rank + suf + ' pire ligne / ' + total + '.';
      }

      var txt = '\u26A0\uFE0F\u26A0\uFE0F Aujourd\u2019hui ' + article + meta.name + ' nous a co\u00FBt\u00E9 ' + coutTxt + '\u00A0\u20AC';
      if (joursLabel) txt += ', soit ' + joursLabel + ' de travail au SMIC.';
      else txt += '.';
      txt += rankTxt;
      txt += '\n\nEt toi, ta ligne nous a co\u00FBt\u00E9 combien\u00A0? \u26A0\uFE0F\u26A0\uFE0F';
      txt += '\n\nhttps://retards-idf.fr';
      return txt;
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

    // URL de la page partageable (og:tags) pour une ligne
    function sharePageUrl(slug) {
      var base = window.location.origin;
      return base + '/share/' + slug + '/today';
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

      // Classement pour le canvas
      var rank = await computeRank(currentLine, days);
      if (rank) data._rank = rank;

      // Image préparée dès l'ouverture du menu (toDataURL synchrone)
      var canvas = buildShareCanvas(meta, data);
      var dataUrl = canvas.toDataURL('image/png');
      var bin = atob(dataUrl.split(',')[1]);
      var buf = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
      var shareFile = new File([buf], 'retards-' + slug + '.png', { type: 'image/png' });

      var text = shareText(meta, data);
      var pageUrl = sharePageUrl(slug);

      // Mobile : Web Share API (fichier image + URL)
      var isMobile = /Mobi|Android/i.test(navigator.userAgent);
      if (isMobile && navigator.share && navigator.canShare && navigator.canShare({ files: [shareFile] })) {
        try {
          await navigator.share({
            text: text,
            url: pageUrl,
            files: [shareFile],
          });
        } catch (_) { /* user cancelled */ }
        return;
      }

      // Desktop : menu avec options
      shareMenu = document.createElement('div');
      shareMenu.className = 'pp-share-menu';

      var items = '';
      // X (Twitter) : texte + lien partageable (og:image s'affichera)
      items +=
        '<button type="button" class="pp-share-item" data-action="x">' +
        '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>' +
        'Partager sur X</button>';
      // Instagram : télécharger l'image
      items +=
        '<button type="button" class="pp-share-item" data-action="instagram">' +
        '<svg viewBox="0 0 24 24" width="18" height="18"><path fill-rule="evenodd" d="M7 2h10a5 5 0 0 1 5 5v10a5 5 0 0 1-5 5H7a5 5 0 0 1-5-5V7a5 5 0 0 1 5-5zm0 2a3 3 0 0 0-3 3v10a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3V7a3 3 0 0 0-3-3H7zm5 3.5a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9zm0 2a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM17.5 5.4a1.1 1.1 0 1 1 0 2.2 1.1 1.1 0 0 1 0-2.2z"/></svg>' +
        'Partager sur Instagram</button>';
      // Télécharger l'image
      items +=
        '<button type="button" class="pp-share-item" data-action="download">' +
        '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M12 16l-6-6h4V4h4v6h4l-6 6z"/><path d="M20 18H4v2h16v-2z"/></svg>' +
        'T\u00E9l\u00E9charger l\u2019image</button>';
      // Copier le lien
      items +=
        '<button type="button" class="pp-share-item" data-action="copy">' +
        '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>' +
        'Copier le lien</button>';

      shareMenu.innerHTML = items;
      ppShare.parentElement.style.position = 'relative';
      ppShare.parentElement.appendChild(shareMenu);

      shareMenu.addEventListener('click', function (ev) {
        var btn = ev.target.closest('[data-action]');
        if (!btn) return;

        if (btn.dataset.action === 'x') {
          window.open('https://twitter.com/intent/tweet?text=' + encodeURIComponent(text), '_blank');
        } else if (btn.dataset.action === 'instagram') {
          if (shareFile) downloadFile(shareFile);
          window.open('https://www.instagram.com/', '_blank');
        } else if (btn.dataset.action === 'download') {
          if (shareFile) downloadFile(shareFile);
        } else if (btn.dataset.action === 'copy') {
          navigator.clipboard.writeText(pageUrl).then(function () {
            btn.textContent = 'Lien copi\u00E9 !';
            setTimeout(closeShareMenu, 1200);
          }).catch(function () {
            // fallback : prompt
            window.prompt('Copiez ce lien :', pageUrl);
          });
          return; // don't close immediately
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
