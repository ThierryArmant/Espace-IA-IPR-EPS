"use strict";
// Referme le menu « Applications » au clic ailleurs ou avec Échap.
const gaufre = document.querySelector("details.gaufre");
if (gaufre) {
  document.addEventListener("click", (event) => {
    if (gaufre.open && !gaufre.contains(event.target)) gaufre.open = false;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") gaufre.open = false;
  });
}
// Logos officiels des applications : affichés s'ils se chargent ; sinon on essaie
// les autres adresses connues (data-autres), puis l'icône de secours reste.
for (const logo of document.querySelectorAll("img.logo-app")) {
  const autres = (logo.dataset.autres || "").split(" ").filter(Boolean);
  const montrer = () => {
    if (logo.naturalWidth > 0) { logo.hidden = false; logo.nextElementSibling.hidden = true; }
  };
  const suivant = () => { if (autres.length) logo.src = autres.shift(); };
  logo.addEventListener("load", montrer);
  logo.addEventListener("error", suivant);
  if (logo.complete) { if (logo.naturalWidth > 0) montrer(); else suivant(); }
}
