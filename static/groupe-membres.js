"use strict";
const filtre = document.getElementById("filtre-membres");
const compte = document.getElementById("compte-membres");
const cases = [...document.querySelectorAll('input[name="members"]')];
function recompter() { compte.textContent = cases.filter((c) => c.checked).length; }
cases.forEach((c) => c.addEventListener("change", recompter));
filtre.addEventListener("input", () => {
  const texte = filtre.value.trim().toLowerCase();
  for (const ligne of document.querySelectorAll(".membre-ligne")) {
    ligne.hidden = texte !== "" && !ligne.textContent.toLowerCase().includes(texte);
  }
});
