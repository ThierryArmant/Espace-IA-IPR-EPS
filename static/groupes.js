"use strict";
// Filtre par nom, « Tout cocher / Tout décocher » par groupe et compteurs.
const cases = [...document.querySelectorAll("input[data-groupe]")];
function recompter() {
  for (const badge of document.querySelectorAll("[data-compte]")) {
    badge.textContent = cases.filter((c) => c.dataset.groupe === badge.dataset.compte && c.checked).length;
  }
}
cases.forEach((c) => c.addEventListener("change", () => { c.closest("td").classList.add("modifie"); recompter(); }));
for (const bouton of document.querySelectorAll("button.tout")) {
  bouton.addEventListener("click", () => {
    for (const c of cases) {
      if (c.dataset.groupe === bouton.dataset.groupe && !c.closest("tr").hidden) {
        c.checked = bouton.dataset.etat === "1";
        c.closest("td").classList.add("modifie");
      }
    }
    recompter();
  });
}
const filtre = document.getElementById("filtre-groupes");
if (filtre) {
  filtre.addEventListener("input", () => {
    const texte = filtre.value.trim().toLowerCase();
    for (const ligne of document.querySelectorAll(".grille-groupes tbody tr")) {
      ligne.hidden = texte !== "" && !ligne.querySelector("th").textContent.toLowerCase().includes(texte);
    }
  });
}
// Fiches « Groupes et accès » : filtre et « Tout cocher » propres à chaque fiche.
for (const fiche of document.querySelectorAll(".fiche-groupe")) {
  const filtreFiche = fiche.querySelector(".filtre-fiche");
  const lignes = [...fiche.querySelectorAll(".liste-membres li")]; // seulement la liste « Ajouter »
  if (filtreFiche) {
    filtreFiche.addEventListener("input", () => {
      const texte = filtreFiche.value.trim().toLowerCase();
      for (const ligne of lignes) ligne.hidden = texte !== "" && !ligne.textContent.toLowerCase().includes(texte);
    });
  }
  for (const bouton of fiche.querySelectorAll("button.tout-fiche")) {
    bouton.addEventListener("click", () => {
      for (const ligne of lignes) if (!ligne.hidden) ligne.querySelector("input").checked = bouton.dataset.etat === "1";
    });
  }
}
