"use strict";
// Messagerie instantanée du Hub : discussions entre membres connectés.
// Un grimpeur descend en rappel pour annoncer un nouveau message.
const racine = document.getElementById("messagerie");
if (racine) {
  const urlEtat = racine.dataset.etat;
  const urlNouvelle = racine.dataset.nouvelle;
  const urlBase = racine.dataset.base.replace(/\/0$/, "");
  const csrf = racine.dataset.csrf;
  const titreOrigine = document.title;
  let etat = { conversations: [], en_ligne: [] };
  let ouverte = null;          // id de la discussion affichée
  let dernierLu = 0;           // dernier message affiché dans la fenêtre
  // id discussion -> dernier message déjà annoncé (gardé d'une page à l'autre).
  let vus = new Map();
  try { vus = new Map(JSON.parse(sessionStorage.getItem("hub-messages-vus") || "[]")); } catch { /* stockage indisponible */ }

  const el = (tag, classe, texte) => {
    const n = document.createElement(tag);
    if (classe) n.className = classe;
    if (texte !== undefined) n.textContent = texte;
    return n;
  };
  const poster = (url, donnees) => fetch(url, {
    method: "POST", body: new URLSearchParams({ csrf, ...donnees }), headers: { Accept: "application/json" },
  });

  // ---------- Bouton et liste des discussions ----------
  const bouton = el("button", "msg-bouton");
  bouton.type = "button";
  bouton.setAttribute("aria-expanded", "false");
  const liste = el("div", "msg-liste");
  liste.hidden = true;
  racine.append(liste, bouton);

  // Quand l'explorateur est affiché, les discussions se rangent à côté des noms dans « ● En ligne ».
  const explorateur = document.querySelector(".sidebar .en-ligne");
  if (explorateur) racine.classList.add("avec-explorateur");
  const dessinerEnLigne = () => {
    if (!explorateur) return;
    const listeEnLigne = explorateur.querySelector(".en-ligne-liste");
    const titreEnLigne = explorateur.querySelector(".en-ligne-titre");
    const nonLus = etat.conversations.reduce((total, c) => total + c.non_lus, 0);
    titreEnLigne.textContent = "";
    titreEnLigne.append(el("span", "point-vert"), `En ligne (${etat.en_ligne.length + 1}) ▾`);
    if (nonLus) titreEnLigne.append(el("span", "msg-pastille", `💬 ${nonLus}`));
    listeEnLigne.textContent = "";
    const moi = el("li", "pastille-personne");
    moi.append(el("span", "point-vert"), `${racine.dataset.moiCourt} (vous)`);
    listeEnLigne.append(moi);
    for (const p of etat.en_ligne) {
      const li = el("li", "pastille-personne");
      li.title = p.nom;
      li.append(el("span", "point-vert"), p.email);
      const aDeux = etat.conversations.find((c) => !c.salon && c.avec.length === 1 && c.avec[0] === p.id);
      const bouton = el("button", "discuter", aDeux && aDeux.non_lus ? `💬 ${aDeux.non_lus} nouveau${aDeux.non_lus > 1 ? "x" : ""}` : "💬 Discuter");
      bouton.type = "button";
      if (aDeux && aDeux.non_lus) bouton.classList.add("discuter-alerte");
      bouton.addEventListener("click", () => (aDeux ? ouvrir(aDeux.id) : demarrer(p.id)));
      li.append(bouton);
      listeEnLigne.append(li);
    }
    // Salons de groupe : une discussion ouverte à tous les membres du groupe.
    if ((etat.salons || []).length) {
      listeEnLigne.append(el("li", "en-ligne-sous-titre", "Salons de mes groupes"));
      for (const salon of etat.salons) {
        const conversation = etat.conversations.find((c) => c.id === salon.conversation);
        const li = el("li", "pastille-personne pastille-groupe");
        li.append(el("span", "", "👥"), el("span", "msg-ligne-titre", `${salon.nom} · ${salon.en_ligne} en ligne`));
        const nonLus = conversation ? conversation.non_lus : 0;
        const bouton = el("button", "discuter", nonLus ? `${nonLus} nouveau${nonLus > 1 ? "x" : ""}` : "Entrer");
        bouton.type = "button";
        if (nonLus) bouton.classList.add("discuter-alerte");
        bouton.addEventListener("click", () => entrerSalon(salon.groupe));
        li.append(bouton);
        listeEnLigne.append(li);
      }
    }
    const autres = etat.conversations.filter((c) => !c.salon && !(c.avec.length === 1 && etat.en_ligne.some((p) => p.id === c.avec[0])));
    if (autres.length) {
      listeEnLigne.append(el("li", "en-ligne-sous-titre", "Discussions en cours"));
      for (const c of autres) {
        const li = el("li", "pastille-personne pastille-groupe");
        li.append(el("span", "", c.avec.length > 1 ? "👥" : "💬"), el("span", "msg-ligne-titre", c.titre));
        const bouton = el("button", "discuter", c.non_lus ? `${c.non_lus} nouveau${c.non_lus > 1 ? "x" : ""}` : "Ouvrir");
        bouton.type = "button";
        if (c.non_lus) bouton.classList.add("discuter-alerte");
        bouton.addEventListener("click", () => ouvrir(c.id));
        li.append(bouton);
        listeEnLigne.append(li);
      }
    }
    if (!etat.en_ligne.length) listeEnLigne.append(el("li", "subtle en-ligne-vide", "Personne d’autre n’est en ligne."));
  };

  const majBouton = () => {
    const nonLus = etat.conversations.reduce((total, c) => total + c.non_lus, 0);
    bouton.textContent = nonLus ? `💬 Discussions · ${nonLus} nouveau${nonLus > 1 ? "x" : ""}` : "💬 Discussions";
    bouton.classList.toggle("msg-alerte", nonLus > 0);
    document.title = nonLus ? `(${nonLus}) ${titreOrigine}` : titreOrigine;
  };

  const dessinerListe = () => {
    liste.textContent = "";
    liste.append(el("h2", "", "Mes discussions"));
    if (!etat.conversations.length) liste.append(el("p", "subtle", "Aucune discussion en cours."));
    for (const c of etat.conversations.filter((x) => !x.salon || x.non_lus)) {
      const ligne = el("button", "msg-ligne");
      ligne.type = "button";
      ligne.append(el("span", "msg-ligne-titre", c.titre));
      if (c.non_lus) ligne.append(el("span", "msg-pastille", String(c.non_lus)));
      ligne.addEventListener("click", () => ouvrir(c.id));
      liste.append(ligne);
    }
    if ((etat.salons || []).length) {
      liste.append(el("h2", "", "Salons de mes groupes"));
      for (const salon of etat.salons) {
        const ligne = el("button", "msg-ligne");
        ligne.type = "button";
        ligne.append(el("span", "", "👥"), el("span", "msg-ligne-titre", `${salon.nom} · ${salon.en_ligne} en ligne`));
        ligne.addEventListener("click", () => entrerSalon(salon.groupe));
        liste.append(ligne);
      }
    }
    liste.append(el("h2", "", "Démarrer avec une personne en ligne"));
    if (!etat.en_ligne.length) liste.append(el("p", "subtle", "Personne d’autre n’est en ligne pour l’instant."));
    for (const p of etat.en_ligne) {
      const ligne = el("button", "msg-ligne");
      ligne.type = "button";
      const point = el("span", "point-vert");
      ligne.append(point, el("span", "msg-ligne-titre", p.email));
      ligne.title = p.nom;
      ligne.addEventListener("click", () => demarrer(p.id));
      liste.append(ligne);
    }
    liste.append(el("p", "subtle msg-note", "Discussions éphémères : effacées 10 minutes après le départ de tous les participants."));
  };
  bouton.addEventListener("click", () => {
    liste.hidden = !liste.hidden;
    bouton.setAttribute("aria-expanded", String(!liste.hidden));
    if (!liste.hidden) dessinerListe();
  });

  // ---------- Fenêtre de discussion ----------
  const fenetre = el("section", "msg-fenetre");
  fenetre.hidden = true;
  fenetre.setAttribute("aria-label", "Discussion");
  const tete = el("div", "msg-tete");
  const titre = el("strong", "msg-titre");
  const actions = el("div", "msg-actions");
  const btnAjouter = el("button", "", "＋");
  btnAjouter.type = "button"; btnAjouter.title = "Ajouter une personne en ligne";
  const btnQuitter = el("button", "", "Quitter");
  btnQuitter.type = "button"; btnQuitter.title = "Quitter cette discussion";
  const btnFermer = el("button", "", "✕");
  btnFermer.type = "button"; btnFermer.title = "Réduire (la discussion continue)";
  actions.append(btnAjouter, btnQuitter, btnFermer);
  tete.append(titre, actions);
  const choixAjout = el("div", "msg-ajout");
  choixAjout.hidden = true;
  const fil = el("ol", "msg-fil");
  fil.setAttribute("aria-live", "polite");
  const saisie = el("form", "msg-saisie");
  const zoneTexte = el("textarea");
  zoneTexte.rows = 2; zoneTexte.maxLength = 1000;
  zoneTexte.placeholder = "Votre message… (Entrée pour envoyer)";
  zoneTexte.setAttribute("aria-label", "Votre message");
  const envoyer = el("button", "", "Envoyer");
  saisie.append(zoneTexte, envoyer);
  fenetre.append(tete, choixAjout, fil, saisie);
  racine.append(fenetre);

  const ajouterMessages = (messages) => {
    const enBas = fil.scrollHeight - fil.scrollTop - fil.clientHeight < 40;
    for (const m of messages) {
      const li = el("li", m.systeme ? "msg-systeme" : (m.moi ? "msg-moi" : ""));
      if (!m.systeme && !m.moi) li.append(el("span", "msg-auteur", m.auteur));
      li.append(el("p", "", m.texte));
      li.append(el("span", "msg-heure", m.heure));
      fil.append(li);
      dernierLu = Math.max(dernierLu, m.id);
    }
    if (messages.length && enBas) fil.scrollTop = fil.scrollHeight;
  };
  const lire = async () => {
    if (ouverte === null) return;
    const reponse = await fetch(`${urlBase}/${ouverte}?apres=${dernierLu}`, { headers: { Accept: "application/json" } });
    if (reponse.status === 404) { fermer(); return; }
    if (!reponse.ok) return;
    const donnees = await reponse.json();
    titre.textContent = donnees.salon ? `👥 ${donnees.titre}` : donnees.titre;
    btnAjouter.hidden = donnees.salon;
    btnQuitter.hidden = donnees.salon;
    titre.title = donnees.membres.map((m) => m.email).join("\n");
    ajouterMessages(donnees.messages);
  };
  const ouvrir = async (id) => {
    cacherGrimpeur();
    liste.hidden = true;
    bouton.setAttribute("aria-expanded", "false");
    if (ouverte !== id) { ouverte = id; dernierLu = 0; fil.textContent = ""; }
    if (explorateur) {
      const bord = document.querySelector(".sidebar").getBoundingClientRect();
      const haut = explorateur.getBoundingClientRect();
      fenetre.style.left = `${Math.round(bord.right + 8)}px`;
      fenetre.style.top = `${Math.max(80, Math.round(haut.top))}px`;
    }
    fenetre.hidden = false;
    choixAjout.hidden = true;
    await lire();
    fil.scrollTop = fil.scrollHeight;
    zoneTexte.focus();
    actualiser();
  };
  const fermer = () => { fenetre.hidden = true; ouverte = null; };
  const entrerSalon = async (groupe) => {
    const reponse = await poster(`${urlBase}/salon/${groupe}`, {});
    if (reponse.ok) ouvrir((await reponse.json()).id);
    else window.alert("Le salon n’a pas pu s’ouvrir. Rechargez la page et réessayez.");
  };
  const demarrer = async (personne) => {
    const reponse = await poster(urlNouvelle, { avec: personne });
    if (reponse.ok) ouvrir((await reponse.json()).id);
    else window.alert("La discussion n’a pas pu démarrer. Rechargez la page et réessayez.");
  };
  btnFermer.addEventListener("click", fermer);
  btnQuitter.addEventListener("click", async () => {
    if (!window.confirm("Quitter cette discussion ? Vous ne recevrez plus ses messages.")) return;
    await poster(`${urlBase}/${ouverte}/quitter`, {});
    fermer();
    actualiser();
  });
  btnAjouter.addEventListener("click", () => {
    choixAjout.textContent = "";
    choixAjout.append(el("p", "subtle", "Ajouter une personne en ligne :"));
    if (!etat.en_ligne.length) choixAjout.append(el("p", "subtle", "Personne d’autre n’est en ligne."));
    for (const p of etat.en_ligne) {
      const choix = el("button", "msg-ligne", p.email);
      choix.type = "button";
      choix.addEventListener("click", async () => {
        await poster(`${urlBase}/${ouverte}/ajouter`, { avec: p.id });
        choixAjout.hidden = true;
        lire();
      });
      choixAjout.append(choix);
    }
    choixAjout.hidden = !choixAjout.hidden;
  });
  saisie.addEventListener("submit", async (event) => {
    event.preventDefault();
    const texte = zoneTexte.value.trim();
    if (!texte || ouverte === null) return;
    const reponse = await poster(`${urlBase}/${ouverte}/envoyer`, { texte });
    if (reponse.ok) { zoneTexte.value = ""; await lire(); fil.scrollTop = fil.scrollHeight; }
    else window.alert("Le message n’a pas pu être envoyé.");
  });
  zoneTexte.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); saisie.requestSubmit(); }
  });

  // Boutons « Discuter » placés dans la page (liste « En ligne » de l'explorateur).
  document.addEventListener("click", (event) => {
    const cible = event.target.closest("[data-discuter]");
    if (cible) { event.preventDefault(); demarrer(Number(cible.dataset.discuter)); }
  });

  // ---------- Le grimpeur ----------
  const grimpeur = el("button", "grimpeur");
  grimpeur.type = "button";
  grimpeur.hidden = true;
  grimpeur.innerHTML = `
    <svg class="grimpeur-dessin" viewBox="0 0 60 220" aria-hidden="true">
      <line x1="30" y1="0" x2="30" y2="150" stroke="#c0392b" stroke-width="2.5" stroke-dasharray="6 3"/>
      <circle cx="30" cy="164" r="9" fill="#f2c9a0"/>
      <path d="M20 162 a10 10 0 0 1 20 0 z" fill="#f39c12"/>
      <rect x="22" y="173" width="16" height="22" rx="5" fill="#2e86de"/>
      <rect x="22" y="188" width="16" height="5" fill="#34495e"/>
      <path d="M24 176 L30 152 M36 176 L30 152" stroke="#f2c9a0" stroke-width="4" stroke-linecap="round"/>
      <path d="M25 194 L18 212 M35 194 L44 208" stroke="#34495e" stroke-width="5" stroke-linecap="round"/>
      <path d="M16 213 h6 M42 209 h6" stroke="#222" stroke-width="4" stroke-linecap="round"/>
    </svg>
    <span class="grimpeur-bulle"><strong>Vous avez un message !</strong><span class="grimpeur-de"></span></span>`;
  document.body.append(grimpeur);
  let minuterieGrimpeur = null;
  let discussionAnnoncee = null;
  let enPresentation = false;
  let toquer = () => {};

  // « Toc toc » fabriqué par le navigateur (aucun fichier son).
  let sonEnAttente = false;
  toquer = () => {
    try {
      const contexte = new (window.AudioContext || window.webkitAudioContext)();
      if (contexte.state === "suspended") { sonEnAttente = true; contexte.close(); return; }
      for (const debut of [0, 0.2]) {
        const oscillateur = contexte.createOscillator();
        const volume = contexte.createGain();
        oscillateur.type = "triangle";
        oscillateur.frequency.setValueAtTime(220, contexte.currentTime + debut);
        oscillateur.frequency.exponentialRampToValueAtTime(90, contexte.currentTime + debut + 0.09);
        volume.gain.setValueAtTime(0.0001, contexte.currentTime + debut);
        volume.gain.exponentialRampToValueAtTime(0.5, contexte.currentTime + debut + 0.005);
        volume.gain.exponentialRampToValueAtTime(0.0001, contexte.currentTime + debut + 0.12);
        oscillateur.connect(volume).connect(contexte.destination);
        oscillateur.start(contexte.currentTime + debut);
        oscillateur.stop(contexte.currentTime + debut + 0.13);
      }
      setTimeout(() => contexte.close(), 600);
    } catch { /* son indisponible */ }
  };
  // Le navigateur n'autorise le son qu'après un premier geste : on rejoue alors le « toc toc ».
  document.addEventListener("pointerdown", () => { if (sonEnAttente) { sonEnAttente = false; toquer(); } }, { once: false });

  const bulle = grimpeur.querySelector(".grimpeur-bulle");
  const presenter = () => {
    enPresentation = true;
    bulle.innerHTML = "";
    const titreBulle = el("strong", "", "Toc toc ! Eh, je suis là… ouvre-moi !");
    const indice = el("span", "grimpeur-de", "Cliquez sur moi");
    bulle.append(titreBulle, indice);
    grimpeur.setAttribute("aria-label", "Présentation de la messagerie : cliquez pour ouvrir");
    placer();
    grimpeur.hidden = false;
    requestAnimationFrame(() => requestAnimationFrame(() => grimpeur.classList.add("descendu")));
    setTimeout(() => { grimpeur.classList.add("toque"); toquer(); }, 1300);
    setTimeout(() => grimpeur.classList.remove("toque"), 2300);
    setTimeout(() => { if (enPresentation && !grimpeur.classList.contains("ouvert")) { grimpeur.classList.add("toque"); toquer(); setTimeout(() => grimpeur.classList.remove("toque"), 1000); } }, 6000);
  };
  const expliquer = () => {
    grimpeur.classList.add("ouvert");
    bulle.innerHTML = "";
    bulle.append(
      el("strong", "", "Salut ! Je suis le grimpeur de la messagerie 🧗"),
      el("span", "grimpeur-texte", "Je descends en rappel chaque fois qu’un collègue vous écrit : cliquez sur moi pour lire son message."),
      el("span", "grimpeur-texte", "Pour écrire à quelqu’un : dans l’explorateur, passez la souris sur « ● En ligne », puis « 💬 Discuter ». Vos discussions sont aussi en bas à droite."),
      el("span", "grimpeur-texte", "Les discussions s’effacent quand tout le monde est parti."),
    );
    const compris = el("span", "grimpeur-compris", "Compris !");
    bulle.append(compris);
  };
  // Le grimpeur descend depuis « ● En ligne » quand l'explorateur est affiché ; sinon depuis le haut de l'écran.
  const placer = () => {
    const ancre = document.querySelector(".sidebar .en-ligne");
    const rect = ancre ? ancre.getBoundingClientRect() : null;
    if (rect && rect.width > 0 && rect.bottom > 0 && rect.bottom < window.innerHeight - 200) {
      grimpeur.classList.add("depuis-connectes");
      grimpeur.style.left = `${Math.round(rect.left + 14)}px`;
      grimpeur.style.top = `${Math.round(rect.bottom - 2)}px`;
    } else {
      grimpeur.classList.remove("depuis-connectes");
      grimpeur.style.left = "";
      grimpeur.style.top = "";
    }
  };
  const cacherGrimpeur = () => {
    grimpeur.classList.remove("descendu");
    clearTimeout(minuterieGrimpeur);
    setTimeout(() => { if (!grimpeur.classList.contains("descendu")) grimpeur.hidden = true; }, 700);
  };
  const cogner = () => {
    grimpeur.classList.remove("toque");
    void grimpeur.offsetWidth;  // relance l'animation
    grimpeur.classList.add("toque");
    toquer();
    setTimeout(() => grimpeur.classList.remove("toque"), 1000);
  };
  const annoncer = (conversation) => {
    // Pas de grimpeur pendant la présentation, ni quand la fenêtre de discussion est ouverte.
    if (enPresentation || enRecap || !fenetre.hidden) return;
    discussionAnnoncee = conversation.id;
    grimpeur.querySelector(".grimpeur-de").textContent = conversation.titre;
    grimpeur.setAttribute("aria-label", `Vous avez un message de ${conversation.titre}. Ouvrir la discussion.`);
    const dejaLa = !grimpeur.hidden && grimpeur.classList.contains("descendu");
    if (!dejaLa) placer();
    grimpeur.hidden = false;
    if (dejaLa) {
      cogner();
    } else {
      requestAnimationFrame(() => requestAnimationFrame(() => grimpeur.classList.add("descendu")));
      setTimeout(cogner, 1300);  // il cogne une fois arrivé en bas
    }
    clearTimeout(minuterieGrimpeur);
    minuterieGrimpeur = setTimeout(cacherGrimpeur, 15000);
  };
  // Récapitulatif des salons de groupe à la connexion.
  let enRecap = false;
  const recapituler = (recap) => {
    enRecap = true;
    discussionAnnoncee = recap[0].id;
    bulle.innerHTML = "";
    bulle.append(el("strong", "", "Pendant votre absence…"));
    for (const salon of recap) {
      bulle.append(el("span", "grimpeur-texte grimpeur-salon", `👥 Salon ${salon.salon} : ${salon.nombre} nouveau${salon.nombre > 1 ? "x" : ""} message${salon.nombre > 1 ? "s" : ""}`));
      for (const m of salon.derniers) bulle.append(el("span", "grimpeur-texte grimpeur-extrait", `${m.auteur} : ${m.texte}`));
    }
    bulle.append(el("span", "grimpeur-compris", recap.length > 1 ? `Ouvrir le salon ${recap[0].salon}` : "Ouvrir le salon"));
    grimpeur.classList.add("ouvert");
    grimpeur.setAttribute("aria-label", "Récapitulatif des salons de groupe : cliquez pour ouvrir");
    placer();
    grimpeur.hidden = false;
    requestAnimationFrame(() => requestAnimationFrame(() => grimpeur.classList.add("descendu")));
    setTimeout(cogner, 1300);
    clearTimeout(minuterieGrimpeur);
    minuterieGrimpeur = setTimeout(() => { finRecap(); cacherGrimpeur(); }, 30000);
  };
  const finRecap = () => {
    enRecap = false;
    grimpeur.classList.remove("ouvert");
    setTimeout(() => { bulle.innerHTML = '<strong>Vous avez un message !</strong><span class="grimpeur-de"></span>'; }, 800);
  };

  grimpeur.addEventListener("click", () => {
    if (enRecap) { const cible = discussionAnnoncee; finRecap(); ouvrir(cible); return; }
    if (enPresentation) {
      if (!grimpeur.classList.contains("ouvert")) { expliquer(); return; }
      enPresentation = false;
      grimpeur.classList.remove("ouvert");
      poster(racine.dataset.presentation, {});
      cacherGrimpeur();
      setTimeout(() => {
        bulle.innerHTML = '<strong>Vous avez un message !</strong><span class="grimpeur-de"></span>';
      }, 800);
      return;
    }
    if (discussionAnnoncee !== null) ouvrir(discussionAnnoncee);
  });

  // ---------- Relevé régulier ----------
  const actualiser = async () => {
    try {
      const reponse = await fetch(urlEtat, { headers: { Accept: "application/json" } });
      if (!reponse.ok) return;
      etat = await reponse.json();
    } catch { return; }
    majBouton();
    dessinerEnLigne();
    if (etat.presentation && !enPresentation && !presentationFaite) { presentationFaite = true; presenter(); }
    else if ((etat.recap || []).length && !enPresentation) {
      recapituler(etat.recap);
      for (const salon of etat.recap) {
        const c = etat.conversations.find((x) => x.id === salon.id);
        if (c) vus.set(c.id, c.dernier);  // déjà annoncé par le récapitulatif
      }
    }
    if (!liste.hidden) dessinerListe();
    for (const c of etat.conversations) {
      const avant = vus.get(c.id) || 0;
      if (c.dernier > avant && c.non_lus > 0 && c.id !== ouverte) annoncer(c);
      vus.set(c.id, c.dernier);
    }
    try { sessionStorage.setItem("hub-messages-vus", JSON.stringify([...vus])); } catch { /* stockage indisponible */ }
    racine.classList.toggle("msg-actif", etat.conversations.length > 0 || etat.en_ligne.length > 0);
  };
  let presentationFaite = false;
  let tour = 0;
  // Relevé léger pour ne pas charger le serveur : toutes les 16 s (onglet visible) ou 2 min
  // (onglet caché) ; la fenêtre de discussion ouverte est relue toutes les 4 s.
  setInterval(() => {
    tour += 1;
    const visible = document.visibilityState === "visible";
    if ((visible && tour % 4 === 0) || tour % 30 === 0) actualiser();
    if (visible && ouverte !== null) lire();
  }, 4000);
  actualiser();
}
