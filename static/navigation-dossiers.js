"use strict";

const dossierLinks = [...document.querySelectorAll("#arborescence a")];
const dossierPanels = [...document.querySelectorAll("[data-dossier]")];

function afficherDossier() {
  const selected = dossierLinks.find((link) => link.hash === location.hash) || dossierLinks[0];
  if (!selected) return;
  for (const link of dossierLinks) {
    if (link === selected) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
  for (const panel of dossierPanels) panel.hidden = "#" + panel.id !== selected.hash;
}

window.addEventListener("hashchange", afficherDossier);
afficherDossier();
