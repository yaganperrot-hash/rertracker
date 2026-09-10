/* ── Durées lisibles : minutes → heures → jours → années ─────
   On bascule vers l'unité supérieure à 2× sa valeur (90 minutes
   plutôt que 1 h 30), puis on affiche unité principale + sous-unité.
   Même logique côté Python dans backend/bot.py (_fmt_duree).     */
(function () {
  const H = 60, J = 1440, A = 525600;

  function n(v) { return v.toLocaleString('fr-FR'); }
  function pl(v, sing, plur) { return v >= 2 ? plur : sing; }

  // court : variante compacte pour tableaux et cellules de stats
  function formatDuree(min, court) {
    min = Math.max(0, Math.floor(min || 0));
    if (min < 2 * H) {
      return court ? `${n(min)} min` : `${n(min)} ${pl(min, 'minute', 'minutes')}`;
    }
    if (min < 2 * J) {
      const h = Math.floor(min / H), m = min % H;
      return m ? `${h} h ${court ? m : m + ' min'}` : `${h} h`;
    }
    if (min < 2 * A) {
      const j = Math.floor(min / J), h = Math.floor((min % J) / H);
      const tete = court ? `${j} j` : `${j} jours`;
      return h ? `${tete} ${h} h` : tete;
    }
    const a = Math.floor(min / A), j = Math.floor((min % A) / J);
    const reste = j ? (court ? ` ${j} j` : ` ${j} ${pl(j, 'jour', 'jours')}`) : '';
    return `${n(a)} ans${reste}`;
  }

  // Accord avec l'unité principale : minutes/heures → féminin, jours/ans → masculin
  function accordPerdu(min) {
    return (min || 0) < 2 * J ? 'perdues' : 'perdus';
  }

  window.formatDuree = formatDuree;
  window.accordPerdu = accordPerdu;
})();
