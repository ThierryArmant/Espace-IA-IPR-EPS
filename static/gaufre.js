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
// Logos officiels des applications : affichés s'ils se chargent, sinon l'icône reste.
for (const logo of document.querySelectorAll("img.logo-app")) {
  const montrer = () => {
    if (logo.naturalWidth > 0) { logo.hidden = false; logo.nextElementSibling.hidden = true; }
  };
  if (logo.complete) montrer(); else logo.addEventListener("load", montrer);
}
