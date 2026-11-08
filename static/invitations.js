"use strict";
// Grise le bouton d’une invitation une fois le brouillon ouvert, pour suivre l’avancement.
for (const button of document.querySelectorAll(".invitation-envoi")) {
  button.addEventListener("click", () => {
    button.classList.add("secondary");
    button.textContent = "Courriel ouvert ✓";
  });
}

// Boutons « Copier » : place le texte dans le presse-papiers.
for (const button of document.querySelectorAll(".copier")) {
  button.addEventListener("click", async () => {
    const label = button.textContent;
    try {
      await navigator.clipboard.writeText(button.dataset.texte);
      button.textContent = "Copié ✓";
    } catch {
      button.textContent = "Copie impossible";
    }
    setTimeout(() => { button.textContent = label; }, 1800);
    button.closest(".invitation-ligne")?.classList.add("invitation-traitee");
  });
}
