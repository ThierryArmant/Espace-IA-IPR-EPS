const creationForms = document.querySelectorAll("[data-nuage-create]");
const creationButtons = [...creationForms].map((form) => form.querySelector("button"));

for (const form of creationForms) {
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const editor = window.open("about:blank", "_blank");
        if (editor) editor.opener = null;
        for (const button of creationButtons) button.disabled = true;
        try {
            const response = await fetch(form.action, {
                method: "POST",
                body: new FormData(form),
                headers: { Accept: "application/json" },
                redirect: "manual",
            });
            if (response.type !== "opaqueredirect" && !response.ok) {
                throw new Error("Création indisponible");
            }
            const result = response.ok ? await response.json() : {};
            if (editor && result.editor) editor.location.replace(result.editor);
            else if (editor) editor.close();
            // Refresh the original folder, including the new document and any notice.
            const folder = new URL(result.folder || window.location.href, window.location.origin);
            folder.searchParams.delete("q");
            window.location.replace(folder);
        } catch {
            if (editor) editor.close();
            for (const button of creationButtons) button.disabled = false;
            window.alert("Création non confirmée. Rechargez le dossier avant de réessayer.");
        }
    });
}
