const el = (id) => document.getElementById(id);
const LABELS = { running: "진행 중", done: "완료", shortfall: "문항 부족", error: "오류", discarded: "폐기됨" };
let shown = 0;

function renderProgress(lines) {
  const list = el("progress");
  for (; shown < lines.length; shown++) {
    const li = document.createElement("li");
    li.textContent = lines[shown];
    list.appendChild(li);
  }
}

function render(data) {
  renderProgress(data.progress);
  el("status").textContent = LABELS[data.status] || data.status;
  el("status").className = "badge " + (data.status === "done" ? "ok" : data.status === "running" ? "" : "bad");
  if (data.error) {
    el("error").textContent = data.error;
    el("error").hidden = false;
  }
  if (data.status === "done") {
    el("done-count").textContent = data.count;
    el("done-id").textContent = data.exam_id;
    el("result-done").hidden = false;
  }
  if (data.status === "shortfall") {
    const list = el("shortfall-list");
    list.replaceChildren();
    Object.entries(data.shortfall || {}).forEach(([type, n]) => {
      const li = document.createElement("li");
      li.textContent = `${type}: ${n}문항 부족`;
      list.appendChild(li);
    });
    el("short-count").textContent = data.count;
    el("log").textContent = (data.log || [])
      .map((e) => {
        const defects = e.defects.map((d) => `[${d.item}] ${d.reason}`).join(" / ");
        return `배치 ${e.batch} · ${e.round}회차 · ${e.type ?? "-"} · ${e.topic ?? "-"}: ${e.passed ? "통과" : defects}`;
      })
      .join("\n");
    el("result-shortfall").hidden = false;
  }
}

async function poll() {
  try {
    const res = await fetch(window.JOB_STATUS_URL);
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    render(data);
    if (data.status === "running") setTimeout(poll, 2000);
  } catch (e) {
    el("error").textContent = "상태를 가져오지 못했습니다. 서버가 종료되었을 수 있습니다.";
    el("error").hidden = false;
  }
}
poll();
