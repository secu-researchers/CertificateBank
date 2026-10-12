const el = (id) => document.getElementById(id);
const LABELS = { running: "채점 중", done: "완료", error: "오류" };
let shown = 0;

async function poll() {
  try {
    const res = await fetch(window.JOB_STATUS_URL);
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    const list = el("progress");
    for (; shown < data.progress.length; shown++) {
      const li = document.createElement("li");
      li.textContent = data.progress[shown];
      list.appendChild(li);
    }
    el("status").textContent = LABELS[data.status] || data.status;
    el("status").className = "badge " + (data.status === "done" ? "ok" : data.status === "running" ? "" : "bad");
    if (data.error) {
      el("error").textContent = data.error;
      el("error").hidden = false;
    }
    if (data.status === "done") {
      window.location.href = window.DONE_URL;
      return;
    }
    if (data.status === "running") setTimeout(poll, 2000);
  } catch (e) {
    el("error").textContent = "상태를 가져오지 못했습니다. 서버가 종료되었을 수 있습니다.";
    el("error").hidden = false;
  }
}
poll();
