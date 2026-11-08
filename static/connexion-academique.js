"use strict";
// Vérifie régulièrement si la connexion académique a été autorisée.
const bloc = document.getElementById("connexion-academique");
const etat = document.getElementById("etat-connexion");
let fini = false;
async function verifier() {
  if (fini) return;
  const donnees = new FormData();
  donnees.append("csrf", bloc.dataset.csrf);
  try {
    const reponse = await fetch(bloc.dataset.verifier, {method: "POST", body: donnees, credentials: "same-origin"});
    const resultat = await reponse.json();
    if (resultat.state === "ok") {
      fini = true;
      etat.textContent = "Connexion réussie, ouverture de l’espace…";
      window.location.href = resultat.next;
      return;
    }
    if (resultat.state !== "waiting") {
      fini = true;
      etat.textContent = resultat.message;
      etat.classList.add("erreur");
      return;
    }
  } catch {
    // Réseau momentanément indisponible : on réessaie.
  }
  setTimeout(verifier, 3000);
}
setTimeout(verifier, 3000);
