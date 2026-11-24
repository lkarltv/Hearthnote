export function initDeletion({ api, navigate, targetFor, requirePin, refresh }) {
  const template = document.querySelector("#delete-confirm-template");
  const notice = document.querySelector("#undo-notice");
  const noticeMessage = document.querySelector("#undo-message");
  const undoButton = document.querySelector("#undo-delete");
  const undo = [];
  let active;

  function close(focus = false) {
    if (!active) return;
    const { button, form } = active;
    active = undefined;
    form.remove();
    button.hidden = false;
    button.setAttribute("aria-expanded", "false");
    if (focus) button.focus();
  }

  function updateUndo() {
    const item = undo.at(-1);
    notice.hidden = !item;
    if (item) noticeMessage.textContent = `${item.label} moved to trash.`;
  }

  function pathFor(item, action = "") {
    return `/api/trash${action}?${new URLSearchParams({ source: item.source })}`;
  }

  for (const controls of document.querySelectorAll("[data-delete]")) {
    const button = controls.querySelector("button");
    button.addEventListener("click", () => {
      const item = targetFor(controls.dataset.delete);
      if (!item) return;
      close();
      const form = template.content.firstElementChild.cloneNode(true);
      const cancel = form.querySelector(".delete-cancel");
      const submit = form.querySelector(".delete-submit");
      const pin = form.querySelector(".delete-pin input");
      const message = form.querySelector(".delete-message");
      active = { button, form };
      function askPin(required) {
        pin.parentElement.hidden = !required;
        pin.required = required;
      }
      const folder = item.payload.kind === "client" || item.payload.kind === "topic";
      form.setAttribute("aria-label", `Confirm deletion of ${item.label}`);
      if (folder) form.querySelector(".delete-question").hidden = false;
      askPin(requirePin());
      button.hidden = true;
      button.setAttribute("aria-expanded", "true");
      controls.append(form);
      (pin.required ? pin : cancel).focus();
      cancel.addEventListener("click", () => close(true));
      form.addEventListener("keydown", (event) => {
        if (event.key !== "Escape" || submit.disabled) return;
        event.stopPropagation();
        close(true);
      });
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (submit.disabled) return;
        const pinValue = pin.value;
        submit.disabled = cancel.disabled = true;
        message.textContent = "";
        try {
          await navigate(async () => {
            let token;
            try {
              ({ token } = await api(pathFor(item), {
                method: "POST",
                body: JSON.stringify({ ...item.payload, pin: pinValue || undefined }),
              }));
            } catch (error) {
              if (error.status === 403) {
                askPin(true);
                pin.value = "";
                pin.focus();
              }
              message.textContent = error.message;
              return;
            }
            undo.push({ ...item, token });
            updateUndo();
            close();
            await refresh(item, false);
            undoButton.focus();
          });
        } finally {
          submit.disabled = cancel.disabled = false;
        }
      });
    });
  }

  undoButton.addEventListener("click", async () => {
    if (!undo.length || undoButton.disabled) return;
    undoButton.disabled = true;
    try {
      await navigate(async () => {
        const item = undo.at(-1);
        await api(pathFor(item, "/undo"), {
          method: "POST",
          body: JSON.stringify({ type: item.mode, token: item.token }),
        });
        undo.pop();
        updateUndo();
        await refresh(item, true);
      });
    } finally {
      undoButton.disabled = false;
      if (!notice.hidden) undoButton.focus();
    }
  });

  return close;
}
