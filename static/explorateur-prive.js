"use strict";

const explorer = document.querySelector(".explorateur-prive");
const entries = [...explorer.querySelectorAll(".explorateur-fleche")].map((button) => ({
  button,
  branch: button.closest(".explorateur-branche"),
  panel: document.getElementById(button.getAttribute("aria-controls")),
}));
const mainEntries = entries.filter(({branch}) => branch.classList.contains("explorateur-racine"));
const desktop = window.matchMedia("(min-width: 841px)");
let openMain = null;
let pinned = false;
let rootCloseTimer;
let rootOpenTimer;
// Délais généreux : la souris doit pouvoir traverser d’autres dossiers sans tout refermer.
const OPEN_DELAY = 250;     // s’arrêter sur un dossier avant qu’il s’ouvre
const SWITCH_DELAY = 450;   // passer d’un dossier principal ouvert à un autre
const CLOSE_DELAY = 800;    // garder le panneau après la sortie de la souris

function setOpen(entry, open) {
  entry.button.setAttribute("aria-expanded", String(open));
  entry.panel.hidden = !open;
}

function fitPanel() {
  if (!openMain) return;
  const {branch, panel} = openMain;
  const top = branch.getBoundingClientRect().top;
  const shift = Math.min(0, Math.max(12 - top, window.innerHeight - 12 - top - panel.offsetHeight));
  panel.style.insetBlockStart = desktop.matches ? `${shift}px` : "";
}

function openRoot(entry, keepOpen = false) {
  clearTimeout(rootCloseTimer);
  if (openMain && openMain !== entry) setOpen(openMain, false);
  if (entry) setOpen(entry, true);
  openMain = entry;
  pinned = keepOpen;
  fitPanel();
}

for (const entry of mainEntries) {
  entry.button.addEventListener("click", () => {
    if (openMain === entry && pinned) openRoot(null);
    else openRoot(entry, true);
  });
  entry.branch.addEventListener("pointerenter", (event) => {
    if (!desktop.matches || event.pointerType !== "mouse") return;
    clearTimeout(rootOpenTimer);
    if (openMain === entry) {
      clearTimeout(rootCloseTimer);
      return;
    }
    if (pinned && openMain) return;
    rootOpenTimer = setTimeout(() => openRoot(entry), openMain ? SWITCH_DELAY : OPEN_DELAY);
  });
  entry.branch.addEventListener("pointerleave", (event) => {
    if (!desktop.matches || event.pointerType !== "mouse") return;
    clearTimeout(rootOpenTimer);
    if (openMain !== entry || pinned) return;
    rootCloseTimer = setTimeout(() => {
      if (!entry.panel.contains(document.activeElement)
          && !entry.branch.querySelector(".folder-actions[open]")) openRoot(null);
    }, CLOSE_DELAY);
  });
}

for (const entry of entries.filter(({branch}) => !branch.classList.contains("explorateur-racine"))) {
  let hoverOpened = false;
  let closeTimer;
  let openTimer;
  entry.button.addEventListener("click", () => {
    clearTimeout(closeTimer);
    setOpen(entry, entry.panel.hidden || hoverOpened);
    hoverOpened = false;
    fitPanel();
  });
  entry.branch.addEventListener("pointerenter", () => clearTimeout(closeTimer));
  const link = entry.branch.querySelector(".explorateur-lien");
  link.addEventListener("pointerenter", (event) => {
    if (desktop.matches && event.pointerType === "mouse" && entry.panel.hidden) {
      openTimer = setTimeout(() => {
        hoverOpened = true;
        setOpen(entry, true);
        fitPanel();
      }, OPEN_DELAY);
    }
  });
  link.addEventListener("pointerleave", () => clearTimeout(openTimer));
  entry.branch.addEventListener("pointerleave", (event) => {
    clearTimeout(openTimer);
    if (!hoverOpened || event.pointerType !== "mouse") return;
    closeTimer = setTimeout(() => {
      if (entry.panel.contains(document.activeElement) || entry.branch.querySelector(".folder-actions[open]")) return;
      setOpen(entry, false);
      hoverOpened = false;
      fitPanel();
    }, CLOSE_DELAY);
  });
}

window.addEventListener("resize", fitPanel);
document.addEventListener("click", (event) => {
  if (openMain && !openMain.branch.contains(event.target)) openRoot(null);
});
explorer.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || !openMain) return;
  openMain.button.focus();
  openRoot(null);
});
