import { api } from "./api.js";
import * as author from "./author.js";
import * as browse from "./browse.js";
import * as compose from "./compose.js";
import * as courses from "./courses.js";
import * as importView from "./import.js";
import * as papersView from "./papers.js";
import * as recycleView from "./recycle.js";
import * as usersView from "./users.js";
import * as session from "./session.js";

function switchView(name) {
  document.querySelectorAll(".tab").forEach(t =>
    t.classList.toggle("active", t.dataset.view === name));
  document.querySelectorAll(".view").forEach(v =>
    v.classList.toggle("active", v.id === "view-" + name));
  if (name === "papers") papersView.refresh();
  if (name === "users") usersView.refresh();
  if (name === "recycle") recycleView.refresh();
}

/** Everything that has to be rebuilt when the teacher switches course. */
async function onCourseChanged(course) {
  session.toast(`Switched to ${course.title}`);
  // The basket belongs to one course's bank, so it does not survive a switch.
  compose.reset();
  author.resetForm();
  await browse.refreshTree();
  await browse.reload();
  await updateBadges();
  document.querySelector('.tab[data-view="browse"]')?.click();
}

async function boot() {
  document.querySelectorAll(".tab").forEach(t =>
    t.addEventListener("click", () => switchView(t.dataset.view)));

  // The account decides which tabs exist, so resolve it before anything else.
  const user = await session.initSession({ onChanged: () => location.reload() });
  session.installAccountMenu();
  const admin = session.isAdmin();
  document.querySelectorAll(".admin-only").forEach(el => { el.hidden = !admin; });
  const signOut = document.getElementById("sign-out");
  if (signOut) signOut.hidden = !user;

  let refreshTreeFn = () => {};
  // The course has to be resolved before anything loads a bank.
  await courses.init({ onSwitch: onCourseChanged });
  courses.installOutsideClick();

  await browse.init({
    onSelect: (q) => compose.add(q),
  }).then(fn => { refreshTreeFn = fn || (() => {}); });

  await compose.init({});
  await importView.init({});
  await papersView.init();
  await author.init();
  await recycleView.init();
  if (admin) await usersView.init();

  // keep the browse context available for "add current topic"
  const origReload = browse.reload;
  window.__browseContext = {};
  const sync = () => { window.__browseContext = browse.currentContext(); };
  document.getElementById("tree").addEventListener("click", () => setTimeout(sync, 30));
  window.addEventListener("bank:changed", async () => {
    await browse.refreshTree();
    await browse.reload();
    sync();
    updateBadges();
  });

  await browse.reload();
  sync();
  await updateBadges();
  return refreshTreeFn;
}

async function updateBadges() {
  try {
    const health = await api.health();
    const eng = document.getElementById("engine-badge");
    if (health.engine) {
      eng.textContent = "TeX: " + health.engine;
      eng.className = "badge";
    } else {
      eng.textContent = "TeX: none (LaTeX export only)";
      eng.className = "badge badge-warn";
    }
    const b = health.bank || {};
    document.getElementById("bank-badge").textContent =
      `${b.total} questions · ${b.images} figures · ${b.needs_review} to review`;
    document.getElementById("bank-badge").className = "badge badge-soft";
  } catch (err) {
    document.getElementById("bank-badge").textContent = "offline";
  }
}

boot();
