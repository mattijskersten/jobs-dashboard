// Poll background task status when a task is running, so the page can flip a
// button from "Running…" to "done/failed" and offer the log — without a reload.
(function () {
  const noteEls = document.querySelectorAll("[data-task-note]");
  if (!noteEls.length) return;

  function anyRunning(tasks) {
    return Object.values(tasks).some((t) => t.status === "running");
  }

  async function poll() {
    let data;
    try {
      data = await (await fetch("/tasks/status")).json();
    } catch (e) {
      return; // transient; try again next tick
    }
    const tasks = data.tasks || {};
    noteEls.forEach((el) => {
      const kind = el.getAttribute("data-task-note");
      const t = tasks[kind];
      if (!t) return;
      el.innerHTML =
        `<a href="#" data-log="${t.log}">${t.status}</a>`;
    });
    // when a running task finishes, reload so server-rendered buttons re-enable
    if (window.__hadRunning && !anyRunning(tasks)) {
      location.reload();
      return;
    }
    window.__hadRunning = anyRunning(tasks);
    if (anyRunning(tasks)) setTimeout(poll, 4000);
  }

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

  poll();
})();
