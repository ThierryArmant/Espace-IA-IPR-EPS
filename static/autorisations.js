"use strict";
// Menus « Tout le tableau / Toute la colonne / Toute la ligne » : remplissent les cases, sans enregistrer.
for (const menu of document.querySelectorAll("select.remplir")) {
  menu.addEventListener("change", () => {
    const value = menu.value;
    if (value === "-") return;
    const target = menu.dataset.cible;
    let selector = "select[data-row]";
    if (target.startsWith("col-")) selector = `tr:not([hidden]) select[data-row][data-col="${target.slice(4)}"]`;
    if (target.startsWith("row-")) selector = `select[data-row="${target.slice(4)}"]`;
    if (target.startsWith("grow-")) selector = `select[data-grow="${target.slice(5)}"]`;
    for (const cell of document.querySelectorAll(selector)) {
      if ([...cell.options].some((option) => option.value === value)) {
        cell.value = value;
        cell.classList.add("modifie");
      }
    }
    menu.value = "-";
  });
}
for (const cell of document.querySelectorAll("select[data-col]")) {
  cell.addEventListener("change", () => cell.classList.add("modifie"));
}

// Filtres : par nom et par groupe (un clic sur « n membre(s) » d’un groupe).
const filtreNom = document.getElementById("filtre-grille");
const filtreGroupe = document.getElementById("filtre-groupe");
const recap = document.getElementById("recap-groupe");
function filtrer() {
  const texte = filtreNom ? filtreNom.value.trim().toLowerCase() : "";
  const groupe = filtreGroupe ? filtreGroupe.value : "";
  let visibles = 0;
  for (const ligne of document.querySelectorAll(".grille-acces tr.ligne-personne")) {
    const nom = ligne.querySelector("th").textContent.toLowerCase();
    const okNom = texte === "" || nom.includes(texte);
    const okGroupe = groupe === "" || ligne.dataset.groupes.includes(` ${groupe} `);
    ligne.hidden = !(okNom && okGroupe);
    if (!ligne.hidden) visibles += 1;
  }
  if (recap) {
    recap.hidden = groupe === "";
    if (groupe) {
      const libelle = filtreGroupe.options[filtreGroupe.selectedIndex].text.replace("Groupe : ", "");
      recap.querySelector("span").textContent = `${visibles} membre(s) de « ${libelle} » affiché(s).`;
    }
  }
}
if (filtreNom) filtreNom.addEventListener("input", filtrer);
if (filtreGroupe) filtreGroupe.addEventListener("change", filtrer);
for (const bouton of document.querySelectorAll(".lien-membres")) {
  bouton.addEventListener("click", () => {
    filtreGroupe.value = filtreGroupe.value === bouton.dataset.groupe ? "" : bouton.dataset.groupe;
    filtrer();
    document.querySelector(".grille-acces tr.ligne-personne:not([hidden])")?.scrollIntoView({block: "center", behavior: "smooth"});
  });
}
const toutAfficher = document.getElementById("tout-afficher");
if (toutAfficher) toutAfficher.addEventListener("click", () => {
  if (filtreNom) filtreNom.value = "";
  filtreGroupe.value = "";
  filtrer();
});
// « Retirer de l'espace » : confirmation avant suppression.
for (const bouton of document.querySelectorAll("button.retirer-personne")) {
  bouton.addEventListener("click", (event) => {
    if (!window.confirm(`Retirer ${bouton.dataset.nom} de l’espace ?\nLa personne perd ses groupes et ses accès ; les documents restent dans leurs dossiers.`)) {
      event.preventDefault();
    }
  });
}
