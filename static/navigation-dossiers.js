"use strict";

const arborescence = document.querySelector("#arborescence");
const dossierLinks = [...arborescence.querySelectorAll(".folder-entry")];
const sousDossierLinks = [...arborescence.querySelectorAll(".sous-dossier")];
const dossierPanels = [...document.querySelectorAll("[data-dossier]")];
const panneauSousDossier = document.querySelector("#panneau-sous-dossier");
const titreSousDossier = document.querySelector("#titre-sous-dossier");
const parentSousDossier = document.querySelector("#parent-sous-dossier");
const branches = [...arborescence.querySelectorAll(".branche-dossier")];
let brancheOuverte = null;
let garderOuverte = false;

function ouvrirBranche(branche, garder = false) {
  brancheOuverte = branche;
  garderOuverte = garder;
  for (const candidate of branches) {
    const visible = candidate === branche;
    candidate.querySelector(".basculer-dossier").setAttribute("aria-expanded", String(visible));
    candidate.querySelector(".sous-dossiers").hidden = !visible;
  }
}

function afficherDossier() {
  const sousDossier = sousDossierLinks.find((link) => link.hash === location.hash);
  const dossier = sousDossier?.closest(".branche-dossier").querySelector(".folder-entry")
    ?? dossierLinks.find((link) => link.hash === location.hash)
    ?? dossierLinks[0];
  const selected = sousDossier ?? dossier;
  for (const link of [...dossierLinks, ...sousDossierLinks]) {
    if (link === selected) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
  for (const panel of dossierPanels) panel.hidden = Boolean(sousDossier) || "#" + panel.id !== dossier.hash;
  panneauSousDossier.hidden = !sousDossier;
  if (sousDossier) {
    titreSousDossier.textContent = sousDossier.textContent.trim();
    parentSousDossier.textContent = dossier.querySelector(".nom-dossier").textContent;
  }
}

for (const branche of branches) {
  const toggle = branche.querySelector(".basculer-dossier");
  const link = branche.querySelector(".folder-entry");
  branche.addEventListener("pointerenter", (event) => {
    if (event.pointerType === "mouse" && brancheOuverte !== branche) ouvrirBranche(branche);
  });
  branche.addEventListener("pointerleave", (event) => {
    if (event.pointerType === "mouse" && brancheOuverte === branche && !garderOuverte
        && !branche.querySelector(".sous-dossiers").contains(document.activeElement)) ouvrirBranche(null);
  });
  toggle.addEventListener("click", () => {
    if (brancheOuverte === branche && garderOuverte) ouvrirBranche(null);
    else ouvrirBranche(branche, true);
  });
  link.addEventListener("click", (event) => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (location.hash !== link.hash) history.pushState(null, "", link.hash);
    afficherDossier();
    ouvrirBranche(branche, true);
  });
}

for (const link of sousDossierLinks) {
  link.addEventListener("click", (event) => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (location.hash !== link.hash) history.pushState(null, "", link.hash);
    afficherDossier();
    ouvrirBranche(null);
    titreSousDossier.focus();
  });
}

document.addEventListener("click", (event) => {
  if (!brancheOuverte?.contains(event.target)) ouvrirBranche(null);
});
arborescence.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || !brancheOuverte) return;
  brancheOuverte.querySelector(".basculer-dossier").focus();
  ouvrirBranche(null);
});
window.addEventListener("hashchange", afficherDossier);
window.addEventListener("popstate", afficherDossier);
afficherDossier();
