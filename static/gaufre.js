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
