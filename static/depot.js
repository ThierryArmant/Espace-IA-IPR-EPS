"use strict";
// Dépôt de fichiers lourds : envoi fichier par fichier, avec progression.
// Le hub transmet chaque fichier directement à Nuage, sans le stocker.
const formulaire = document.querySelector("form.depot-fichiers[data-gros]");
if (formulaire) {
  const zone = formulaire.querySelector(".progression-depot");
  const champ = formulaire.querySelector('input[type="file"]');
  const bouton = formulaire.querySelector("button");
  const envoyer = (fichier) => new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    const ligne = document.createElement("p");
    const barre = document.createElement("progress");
    barre.max = 100; barre.value = 0;
    ligne.textContent = `${fichier.name} : `;
    ligne.append(barre);
    const etat = document.createElement("span");
    ligne.append(etat);
    zone.append(ligne);
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        barre.value = Math.round((event.loaded / event.total) * 100);
        etat.textContent = ` ${barre.value} %`;
      }
    });
    xhr.addEventListener("load", () => {
      let message = "Erreur inattendue.";
      try { message = JSON.parse(xhr.responseText).message; } catch { /* réponse non JSON */ }
      if (xhr.status === 413 && !message.includes("lourd")) message = "Fichier trop lourd pour le serveur.";
      etat.textContent = xhr.status === 200 ? " ✓ déposé" : ` ✗ ${message}`;
      resolve(xhr.status === 200);
    });
    xhr.addEventListener("error", () => { etat.textContent = " ✗ transfert interrompu (connexion)."; resolve(false); });
    xhr.open("PUT", formulaire.dataset.gros);
    xhr.setRequestHeader("X-CSRF-Token", formulaire.dataset.csrf);
    xhr.setRequestHeader("X-Nom", encodeURIComponent(fichier.name));
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.send(fichier);
  });
  formulaire.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fichiers = [...champ.files];
    if (!fichiers.length) return;
    bouton.disabled = true;
    zone.textContent = "";
    let tousOk = true;
    for (const fichier of fichiers) {
      tousOk = (await envoyer(fichier)) && tousOk;
    }
    bouton.disabled = false;
    const fin = document.createElement("p");
    fin.textContent = tousOk ? "Terminé. Mise à jour de la liste…" : "Certains fichiers n’ont pas été déposés (voir ci-dessus).";
    zone.append(fin);
    if (tousOk) setTimeout(() => window.location.reload(), 900);
  });
}
