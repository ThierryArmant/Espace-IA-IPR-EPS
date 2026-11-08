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
    clearTimeout(rootCloseTimer);
    if (openMain !== entry) openRoot(entry);
  });
  entry.branch.addEventListener("pointerleave", (event) => {
    if (!desktop.matches || event.pointerType !== "mouse" || openMain !== entry || pinned) return;
    rootCloseTimer = setTimeout(() => {
      if (!entry.panel.contains(document.activeElement)
          && !entry.branch.querySelector(".folder-actions[open]")) openRoot(null);
    }, 180);
  });
}

for (const entry of entries.filter(({branch}) => !branch.classList.contains("explorateur-racine"))) {
  let hoverOpened = false;
  let closeTimer;
  entry.button.addEventListener("click", () => {
    clearTimeout(closeTimer);
    setOpen(entry, entry.panel.hidden || hoverOpened);
    hoverOpened = false;
    fitPanel();
  });
  entry.branch.addEventListener("pointerenter", () => clearTimeout(closeTimer));
  entry.branch.querySelector(".explorateur-lien").addEventListener("pointerenter", (event) => {
    if (desktop.matches && event.pointerType === "mouse" && entry.panel.hidden) {
      hoverOpened = true;
      setOpen(entry, true);
      fitPanel();
    }
  });
  entry.branch.addEventListener("pointerleave", (event) => {
    if (!hoverOpened || event.pointerType !== "mouse") return;
    closeTimer = setTimeout(() => {
      if (entry.panel.contains(document.activeElement) || entry.branch.querySelector(".folder-actions[open]")) return;
      setOpen(entry, false);
      hoverOpened = false;
      fitPanel();
    }, 180);
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
