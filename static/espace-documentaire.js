import { jaliosEndpoint } from "./jalios-config.js";

const academyOrigin = "https://www.pedagogie.ac-aix-marseille.fr";
const status = document.querySelector("#etat");
const folders = document.querySelector("#dossiers");
const files = document.querySelector("#fichiers");
const title = document.querySelector("#titre");
const empty = document.querySelector("#vide");
const form = document.querySelector("#formulaire");
const controls = document.querySelector("#depot-commandes");
const fileInput = form.elements.namedItem("file");
let currentFolder = null;
let uploadToken = null;
let busy = false;

function academicUrl(value) {
  const url = new URL(value, academyOrigin);
  if (url.origin !== academyOrigin || url.username || url.password) {
    throw new Error("Adresse Jalios non reconnue.");
  }
  return url;
}

async function callJalios(folderId, options = {}) {
  const url = academicUrl(jaliosEndpoint);
  if (folderId !== null) url.searchParams.set("folder", folderId);
  const response = await fetch(url, {
    ...options,
    credentials: "include",
    cache: "no-store",
    redirect: "error",
    headers: { Accept: "application/json", ...options.headers },
  });
  if (response.status === 401) {
    throw new Error("Reconnectez-vous dans Jalios, puis rouvrez IA-IPR EPS depuis le site académique.");
  }
  if (response.status === 403) throw new Error("Jalios refuse l’accès à ce dossier ou cette opération.");
  if (!response.ok || !response.headers.get("Content-Type")?.includes("application/json")) {
    throw new Error("Jalios n’a pas confirmé l’opération.");
  }
  return response.json();
}

function folderButton(label, id) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "root secondary";
  button.textContent = label;
  button.addEventListener("click", () => loadFolder(id));
  return button;
}

function render(data) {
  if (typeof data.folder?.id !== "string" || typeof data.folder?.name !== "string"
      || !Array.isArray(data.folders) || !Array.isArray(data.files)) {
    throw new Error("La réponse de Jalios ne correspond pas à l’espace documentaire.");
  }
  const folderElements = data.folders.map((child) => folderButton(child.name, child.id));
  const fileElements = data.files.map((file) => {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.textContent = file.name;
    link.href = academicUrl(file.url).href;
    link.rel = "noreferrer";
    item.append(link);
    return item;
  });
  folders.replaceChildren(folderButton("Racine IA-IPR EPS", null), ...folderElements);
  files.replaceChildren(...fileElements);
  empty.hidden = fileElements.length > 0;
  title.textContent = data.folder.name;
  currentFolder = data.folder.id;
  uploadToken = data.canUpload === true && typeof data.csrfToken === "string" && data.csrfToken
    ? data.csrfToken : null;
}

async function loadFolder(folderId, success = "") {
  if (busy) return;
  busy = true;
  controls.disabled = true;
  currentFolder = null;
  uploadToken = null;
  form.reset();
  files.replaceChildren();
  empty.hidden = true;
  status.textContent = "Chargement depuis Jalios…";
  try {
    render(await callJalios(folderId));
    status.textContent = success || (uploadToken ? "Dépôt autorisé dans ce dossier." : "Consultation des documents.");
  } catch (error) {
    status.textContent = success
      ? success + " La liste n’a pas pu être actualisée."
      : error.message;
  } finally {
    busy = false;
    controls.disabled = !uploadToken;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || !uploadToken || !currentFolder) return;
  const selected = fileInput.files[0];
  if (!selected || !selected.name.toLowerCase().endsWith(".pdf")) {
    status.textContent = "Choisissez un fichier PDF.";
    return;
  }
  const folderId = currentFolder;
  const data = new FormData(form);
  busy = true;
  controls.disabled = true;
  status.textContent = "Dépôt du PDF dans Jalios…";
  try {
    const result = await callJalios(folderId, {
      method: "POST", body: data, headers: { "X-CSRF-Token": uploadToken },
    });
    if (result.uploaded !== true) throw new Error("Le dépôt n’a pas été confirmé par Jalios.");
  } catch (error) {
    status.textContent = error.message;
    busy = false;
    controls.disabled = false;
    return;
  }
  busy = false;
  await loadFolder(folderId, "PDF déposé dans Jalios.");
});

if (jaliosEndpoint) loadFolder(null);
