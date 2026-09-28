const state = {
  contacts: window.INITIAL_DATA.contacts,
  drafts: [],
  token: null,
};

const $ = (id) => document.getElementById(id);
const list = $("contact-list");
const count = $("recipient-count");
const toast = $("toast");

$("subject").value = window.INITIAL_DATA.subject;
$("message").value = window.INITIAL_DATA.message;

function showToast(message, error = false) {
  toast.textContent = message;
  toast.className = `toast${error ? " error" : ""}`;
  setTimeout(() => toast.classList.add("hidden"), 3600);
}

function contactRow(contact = { name: "", email: "" }) {
  const element = document.createElement("div");
  element.className = "contact-row";

  const name = document.createElement("input");
  name.placeholder = "Full name";
  name.value = contact.name;
  name.setAttribute("aria-label", "Name");

  const email = document.createElement("input");
  email.type = "email";
  email.placeholder = "friend@example.com";
  email.value = contact.email;
  email.setAttribute("aria-label", "Email address");

  const remove = document.createElement("button");
  remove.className = "remove";
  remove.textContent = "×";
  remove.setAttribute("aria-label", "Remove recipient");
  remove.onclick = () => {
    element.remove();
    syncCount();
  };
  element.append(name, email, remove);
  return element;
}

function renderContacts() {
  list.replaceChildren(...state.contacts.map(contactRow));
  syncCount();
}

function syncCount() {
  count.textContent = list.children.length;
}

function fillSelector(id, names, selected) {
  const select = $(id);
  select.replaceChildren(
    ...names.map((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      option.selected = name === selected;
      return option;
    }),
  );
}

function payload() {
  return {
    contacts: [...list.children].map((element) => ({
      name: element.children[0].value,
      email: element.children[1].value,
    })),
    subject: $("subject").value,
    message: $("message").value,
    noai: !$("use-ai").checked,
    model: $("model").value,
    contactFile: $("contact-file").value,
    messageFile: $("message-file").value,
  };
}

async function api(path, data) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error(result.error || "Request failed");
  return result;
}

function busy(button, enabled, label) {
  if (enabled) {
    button.dataset.label = button.textContent;
    button.textContent = label;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.label;
    button.disabled = false;
  }
}

function renderDrafts(drafts) {
  const visibleDrafts = drafts.slice(0, 2);
  const cards = visibleDrafts.map((draft) => {
    const card = document.createElement("article");
    card.className = "draft";
    const meta = document.createElement("div");
    meta.className = "draft-meta";
    const person = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = draft.name;
    const email = document.createElement("span");
    email.textContent = draft.email;
    person.append(strong, email);
    const subject = document.createElement("div");
    subject.className = "draft-subject";
    subject.textContent = draft.subject;
    meta.append(person, subject);
    const body = document.createElement("div");
    body.className = "draft-body";
    body.textContent = draft.body;
    card.append(meta, body);
    return card;
  });
  $("drafts").replaceChildren(...cards);
  $("preview-summary").textContent =
    drafts.length > 2
      ? `Showing the first 2 of ${drafts.length} emails. The full batch will still be sent.`
      : `Showing all ${drafts.length} email${drafts.length === 1 ? "" : "s"}.`;
  $("preview-section").classList.remove("hidden");
  return drafts.length;
}

async function createPreview(button, scroll = true) {
  busy(button, true, "Creating previews…");
  try {
    const result = await api("/api/preview", payload());
    state.drafts = result.drafts;
    state.token = result.token;
    const total = renderDrafts(result.drafts);
    if (scroll) $("preview-section").scrollIntoView({ behavior: "smooth" });
    showToast(`${total} previews ready`);
    return true;
  } catch (error) {
    showToast(error.message, true);
    return false;
  } finally {
    busy(button, false);
  }
}

function openSendConfirmation() {
  const phrase = `SEND ${state.drafts.length}`;
  $("confirmation-label").textContent = phrase;
  $("confirmation").value = "";
  $("confirm-send").disabled = true;
  $("modal").classList.remove("hidden");
  $("confirmation").focus();
}

$("add-contact").onclick = () => {
  list.append(contactRow());
  syncCount();
  list.lastElementChild.children[0].focus();
};

$("contact-file").onchange = async (event) => {
  try {
    const result = await api("/api/load", { kind: "contacts", name: event.target.value });
    state.contacts = result.contacts;
    renderContacts();
    state.token = null;
    showToast(`Loaded ${event.target.value}`);
  } catch (error) {
    showToast(error.message, true);
  }
};

$("message-file").onchange = async (event) => {
  try {
    const result = await api("/api/load", { kind: "messages", name: event.target.value });
    $("message").value = result.message;
    $("subject").value = result.subject;
    state.token = null;
    $("save-status").textContent = event.target.value;
    showToast(`Loaded ${event.target.value}`);
  } catch (error) {
    showToast(error.message, true);
  }
};

$("save").onclick = async () => {
  const button = $("save");
  busy(button, true, "Saving…");
  try {
    await api("/api/save", payload());
    showToast("Selected files saved");
    $("save-status").textContent = `${$("message-file").value} · saved`;
  } catch (error) {
    showToast(error.message, true);
  } finally {
    busy(button, false);
  }
};

$("preview").onclick = () => createPreview($("preview"));
$("send-now").onclick = async () => {
  const button = $("send-now");
  if (!(await createPreview(button, false))) return;
  busy(button, true, "Sending now…");
  try {
    const result = await api("/api/send", { token: state.token, immediate: true });
    state.token = null;
    $("open-send").disabled = true;
    showToast(`Sent ${result.sent.length} emails · saved to logs`);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    busy(button, false);
  }
};
$("open-send").onclick = openSendConfirmation;
$("cancel-send").onclick = () => $("modal").classList.add("hidden");
$("confirmation").oninput = (event) => {
  $("confirm-send").disabled = event.target.value !== `SEND ${state.drafts.length}`;
};
$("confirm-send").onclick = async () => {
  const button = $("confirm-send");
  busy(button, true, "Sending…");
  try {
    const result = await api("/api/send", {
      token: state.token,
      confirmation: $("confirmation").value,
    });
    $("modal").classList.add("hidden");
    state.token = null;
    showToast(`Sent ${result.sent.length} emails successfully`);
    $("open-send").disabled = true;
  } catch (error) {
    showToast(error.message, true);
  } finally {
    busy(button, false);
  }
};
$("use-ai").onchange = () => {
  $("model").disabled = !$("use-ai").checked;
};

fillSelector("contact-file", window.INITIAL_DATA.contactFiles, window.INITIAL_DATA.contactFile);
fillSelector("message-file", window.INITIAL_DATA.messageFiles, window.INITIAL_DATA.messageFile);
renderContacts();
