// Poll background state so the page can update without a manual reload:
//  - background tasks (ingest/tailor): flip a button from "Running…" to done/failed
//  - a Refine (Remote) session: flip "Launching…" to the live URL + QR once ready
(function () {
  const noteEls = document.querySelectorAll("[data-task-note]");
  const refineEl = document.querySelector("[data-refine]");
  const jobId = (location.pathname.match(/\/job\/([^/]+)/) || [])[1];

  function anyTaskRunning(tasks) {
    return Object.values(tasks).some((t) => t.status === "running");
  }
  function refineLaunching() {
    return refineEl && refineEl.getAttribute("data-rc-status") === "launching";
  }
  function scheduleNext() {
    if (window.__hadRunning || refineLaunching()) setTimeout(poll, 3000);
  }

  async function poll() {
    let data;
    try {
      data = await (await fetch("/tasks/status")).json();
    } catch (e) {
      return scheduleNext(); // transient; try again next tick
    }
    const tasks = data.tasks || {};
    const sessions = data.sessions || {};

    noteEls.forEach((el) => {
      const kind = el.getAttribute("data-task-note");
      const t = tasks[kind];
      if (!t) return;
      el.innerHTML = `<a href="#" data-log="${t.log}">${t.status}</a>`;
    });

    // reload when a running task finishes, so server-rendered buttons re-enable
    if (window.__hadRunning && !anyTaskRunning(tasks)) {
      location.reload();
      return;
    }
    window.__hadRunning = anyTaskRunning(tasks);

    // reload when our refine session leaves "launching" (→ live URL+QR, or ended)
    if (refineLaunching() && jobId && sessions[jobId]) {
      if (sessions[jobId].status !== "launching") {
        location.reload();
        return;
      }
    }

    scheduleNext();
  }

  // "continue here" in the Refine panel: copy the shell command to resume the
  // tailoring session. Falls back to a selectable prompt in non-secure contexts
  // (plain http over Tailscale), where navigator.clipboard is unavailable.
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("a.cmd-copy");
    if (!a) return;
    ev.preventDefault();
    const cmd = a.getAttribute("data-cmd") || "";
    const flash = () => {
      const prev = a.textContent;
      a.textContent = "copied ✓";
      setTimeout(() => (a.textContent = prev), 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(cmd).then(flash, () => window.prompt("Resume command:", cmd));
    } else {
      window.prompt("Resume command:", cmd);
    }
  });

  // show a log tail when a status link is tapped
  document.addEventListener("click", async (ev) => {
    const a = ev.target.closest("a[data-log]");
    if (!a) return;
    ev.preventDefault();
    const log = a.getAttribute("data-log");
    const data = await (
      await fetch("/tasks/status?log=" + encodeURIComponent(log))
    ).json();
    alert(data.log_tail || "(no log output yet)");
  });

  if (noteEls.length || refineLaunching()) poll();
})();
