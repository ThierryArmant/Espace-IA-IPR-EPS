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

function setOpen(entry, open) {
  entry.button.setAttribute("aria-expanded", String(open));
  entry.panel.hidden = !open;
}

function openRoot(entry, keepOpen = false) {
  if (openMain && openMain !== entry) setOpen(openMain, false);
  if (entry) setOpen(entry, true);
  openMain = entry;
  pinned = keepOpen;
}

for (const entry of mainEntries) {
  entry.button.addEventListener("click", () => {
    if (openMain === entry && pinned) openRoot(null);
    else openRoot(entry, true);
  });
  entry.branch.addEventListener("pointerenter", (event) => {
    if (desktop.matches && event.pointerType === "mouse" && openMain !== entry) openRoot(entry);
  });
  entry.branch.addEventListener("pointerleave", (event) => {
    if (desktop.matches && event.pointerType === "mouse" && openMain === entry && !pinned
        && !entry.branch.contains(document.activeElement)
        && !entry.branch.querySelector(".folder-actions[open]")) openRoot(null);
  });
}

for (const entry of entries.filter(({branch}) => !branch.classList.contains("explorateur-racine"))) {
  entry.button.addEventListener("click", () => setOpen(entry, entry.panel.hidden));
  entry.branch.querySelector(".explorateur-lien").addEventListener("pointerenter", (event) => {
    if (desktop.matches && event.pointerType === "mouse") setOpen(entry, true);
  });
}

document.addEventListener("click", (event) => {
  if (openMain && !openMain.branch.contains(event.target)) openRoot(null);
});
explorer.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || !openMain) return;
  openMain.button.focus();
  openRoot(null);
});
