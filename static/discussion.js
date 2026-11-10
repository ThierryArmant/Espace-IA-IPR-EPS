"use strict";
// Discussion de l'espace : lecture toutes les 8 secondes, envoi par Entrée.
const zone = document.querySelector(".discussion");
if (zone) {
  const fil = zone.querySelector(".discussion-fil");
  const formulaire = zone.querySelector(".discussion-envoi");
  const texte = formulaire.querySelector("textarea");
  let dernier = 0;
  let premier = true;

  const ligne = (message) => {
    const li = document.createElement("li");
    li.dataset.id = message.id;
    if (message.moi) li.classList.add("moi");
    const tete = document.createElement("div");
    tete.className = "discussion-tete";
    const auteur = document.createElement("strong");
    auteur.textContent = message.auteur;
    if (message.nom) auteur.title = message.nom;
    const heure = document.createElement("span");
    heure.className = "subtle";
    heure.textContent = ` ${message.heure}`;
    tete.append(auteur, heure);
    if (message.supprimable) {
      const croix = document.createElement("button");
      croix.type = "button";
      croix.className = "discussion-suppr";
      croix.textContent = "✕";
      croix.title = "Supprimer ce message";
      croix.addEventListener("click", async () => {
        if (!window.confirm("Supprimer ce message ?")) return;
        const corps = new URLSearchParams({ csrf: zone.dataset.csrf });
        const reponse = await fetch(zone.dataset.suppr.replace(/\/0\/supprimer$/, `/${message.id}/supprimer`), { method: "POST", body: corps });
        if (reponse.ok) li.remove();
      });
      tete.append(croix);
    }
    const corps = document.createElement("p");
    corps.textContent = message.texte;
    li.append(tete, corps);
    return li;
  };

  const charger = async () => {
    try {
      const reponse = await fetch(`${zone.dataset.url}?apres=${dernier}`, { headers: { Accept: "application/json" } });
      if (!reponse.ok) return;
      const donnees = await reponse.json();
      if (premier) { fil.textContent = ""; premier = false; }
      const existants = new Set(donnees.existants);
      for (const li of [...fil.querySelectorAll("li[data-id]")]) {
        if (!existants.has(Number(li.dataset.id))) li.remove();
      }
      const enBas = fil.scrollHeight - fil.scrollTop - fil.clientHeight < 40;
      for (const message of donnees.messages) {
        fil.append(ligne(message));
        dernier = Math.max(dernier, message.id);
      }
      if (!fil.querySelector("li")) {
        const vide = document.createElement("li");
        vide.className = "subtle vide";
        vide.textContent = "Aucun message pour l’instant.";
        fil.append(vide);
      } else {
        fil.querySelector("li.vide")?.remove();
      }
      if (donnees.messages.length && enBas) fil.scrollTop = fil.scrollHeight;
    } catch { /* réseau momentanément indisponible : on réessaie plus tard */ }
  };

  formulaire.addEventListener("submit", async (event) => {
    event.preventDefault();
    const valeur = texte.value.trim();
    if (!valeur) return;
    const corps = new URLSearchParams({ csrf: zone.dataset.csrf, texte: valeur });
    const reponse = await fetch(zone.dataset.envoi, { method: "POST", body: corps });
    if (reponse.ok) {
      texte.value = "";
      await charger();
      fil.scrollTop = fil.scrollHeight;
    } else {
      window.alert("Le message n’a pas pu être envoyé. Rechargez la page et réessayez.");
    }
  });
  texte.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); formulaire.requestSubmit(); }
  });

  charger().then(() => { fil.scrollTop = fil.scrollHeight; });
  // Onglet visible : toutes les 8 s ; onglet caché : toutes les minutes (la discussion reste « ouverte »).
  let compteur = 0;
  setInterval(() => {
    compteur += 1;
    if (document.visibilityState === "visible" || compteur % 8 === 0) charger();
  }, 8000);
}
