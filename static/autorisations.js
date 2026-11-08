"use strict";
// Menus « Tout le tableau / Toute la colonne / Toute la ligne » : remplissent les cases, sans enregistrer.
for (const menu of document.querySelectorAll("select.remplir")) {
  menu.addEventListener("change", () => {
    const value = menu.value;
    if (value === "-") return;
    const target = menu.dataset.cible;
    let selector = "select[data-col]";
    if (target.startsWith("col-")) selector = `select[data-col="${target.slice(4)}"]`;
    if (target.startsWith("row-")) selector = `select[data-row="${target.slice(4)}"]`;
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

// Filtre des lignes par nom ou adresse.
const filtre = document.getElementById("filtre-grille");
if (filtre) {
  filtre.addEventListener("input", () => {
    const texte = filtre.value.trim().toLowerCase();
    for (const ligne of document.querySelectorAll(".grille-acces tbody tr")) {
      const nom = ligne.querySelector("th").textContent.toLowerCase();
      ligne.hidden = texte !== "" && !nom.includes(texte);
    }
  });
}
