"use strict";
// Grise le bouton d’une invitation une fois le brouillon ouvert, pour suivre l’avancement.
for (const button of document.querySelectorAll(".invitation-envoi")) {
  button.addEventListener("click", () => {
    button.classList.add("secondary");
    button.textContent = "Courriel ouvert ✓";
  });
}
