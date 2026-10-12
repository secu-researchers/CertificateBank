(() => {
  const form = document.getElementById("solve-form");
  const key = `cb-draft-${form.dataset.examId}`;
  const store = {
    get() { try { return JSON.parse(localStorage.getItem(key) || "{}"); } catch { return {}; } },
    set(v) { try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* 저장소를 쓸 수 없으면 무시 */ } },
    clear() { try { localStorage.removeItem(key); } catch { /* 무시 */ } },
  };

  const fields = () => [...form.elements].filter((el) => /^q\d+$/.test(el.name));

  // 임시 저장 복원
  const draft = store.get();
  fields().forEach((el) => {
    if (!(el.name in draft)) return;
    if (el.type === "radio") el.checked = el.value === draft[el.name];
    else el.value = draft[el.name];
  });

  const save = () => {
    const data = {};
    fields().forEach((el) => {
      if (el.type === "radio") { if (el.checked) data[el.name] = el.value; }
      else if (el.value) data[el.name] = el.value;
    });
    store.set(data);
  };
  form.addEventListener("input", save);
  form.addEventListener("change", save);

  // 경과 시간
  const started = Date.now();
  const timer = document.getElementById("timer");
  const elapsed = () => Math.floor((Date.now() - started) / 1000);
  setInterval(() => {
    const s = elapsed();
    timer.textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }, 1000);

  const answered = () => {
    const names = new Set();
    fields().forEach((el) => {
      if (el.type === "radio" ? el.checked : el.value.trim() !== "") names.add(el.name);
    });
    return names.size;
  };

  form.addEventListener("submit", (e) => {
    const total = Number(form.dataset.total);
    const empty = total - answered();
    if (empty > 0 && !confirm(`${empty}문항이 비어 있습니다. 제출할까요?`)) {
      e.preventDefault();
      return;
    }
    document.getElementById("elapsed_sec").value = elapsed();
    store.clear();
  });

  document.getElementById("clear-draft").addEventListener("click", () => {
    if (!confirm("입력한 내용을 모두 지울까요?")) return;
    form.reset();
    store.clear();
  });
})();
