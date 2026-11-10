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
    for (const c of etat.conversations) {
      const ligne = el("button", "msg-ligne");
      ligne.type = "button";
      ligne.append(el("span", "msg-ligne-titre", c.titre));
      if (c.non_lus) ligne.append(el("span", "msg-pastille", String(c.non_lus)));
      ligne.addEventListener("click", () => ouvrir(c.id));
      liste.append(ligne);
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
    titre.textContent = donnees.titre;
    titre.title = donnees.membres.map((m) => m.email).join("\n");
    ajouterMessages(donnees.messages);
  };
  const ouvrir = async (id) => {
    cacherGrimpeur();
    liste.hidden = true;
    bouton.setAttribute("aria-expanded", "false");
    if (ouverte !== id) { ouverte = id; dernierLu = 0; fil.textContent = ""; }
    fenetre.hidden = false;
    choixAjout.hidden = true;
    await lire();
    fil.scrollTop = fil.scrollHeight;
    zoneTexte.focus();
    actualiser();
  };
  const fermer = () => { fenetre.hidden = true; ouverte = null; };
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
  const cacherGrimpeur = () => {
    grimpeur.classList.remove("descendu");
    clearTimeout(minuterieGrimpeur);
    setTimeout(() => { if (!grimpeur.classList.contains("descendu")) grimpeur.hidden = true; }, 700);
  };
  const annoncer = (conversation) => {
    discussionAnnoncee = conversation.id;
    grimpeur.querySelector(".grimpeur-de").textContent = conversation.titre;
    grimpeur.setAttribute("aria-label", `Vous avez un message de ${conversation.titre}. Ouvrir la discussion.`);
    grimpeur.hidden = false;
    requestAnimationFrame(() => requestAnimationFrame(() => grimpeur.classList.add("descendu")));
    clearTimeout(minuterieGrimpeur);
    minuterieGrimpeur = setTimeout(cacherGrimpeur, 12000);
  };
  grimpeur.addEventListener("click", () => { if (discussionAnnoncee !== null) ouvrir(discussionAnnoncee); });

  // ---------- Relevé régulier ----------
  const actualiser = async () => {
    try {
      const reponse = await fetch(urlEtat, { headers: { Accept: "application/json" } });
      if (!reponse.ok) return;
      etat = await reponse.json();
    } catch { return; }
    majBouton();
    if (!liste.hidden) dessinerListe();
    for (const c of etat.conversations) {
      const avant = vus.get(c.id) || 0;
      if (c.dernier > avant && c.non_lus > 0 && c.id !== ouverte) annoncer(c);
      vus.set(c.id, c.dernier);
    }
    try { sessionStorage.setItem("hub-messages-vus", JSON.stringify([...vus])); } catch { /* stockage indisponible */ }
    racine.classList.toggle("msg-actif", etat.conversations.length > 0 || etat.en_ligne.length > 0);
  };
  let tour = 0;
  setInterval(() => {
    tour += 1;
    const visible = document.visibilityState === "visible";
    if (visible || tour % 15 === 0) actualiser();
    if (visible && ouverte !== null) lire();
  }, 4000);
  actualiser();
}
