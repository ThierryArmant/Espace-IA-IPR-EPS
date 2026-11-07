"use strict";

const password = document.getElementById("mot-de-passe");
const visibility = document.getElementById("visibilite-mot-de-passe");

visibility.hidden = false;
visibility.addEventListener("click", () => {
  const reveal = password.type === "password";
  password.type = reveal ? "text" : "password";
  visibility.textContent = reveal ? "Masquer" : "Afficher";
});
