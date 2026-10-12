const certSelect = document.getElementById("cert");

function applyPreset() {
  const preset = (window.CERT_PRESETS || {})[certSelect.value] || { counts: {}, points: {} };
  document.querySelectorAll("input[data-kind]").forEach((input) => {
    const isCount = input.dataset.kind === "count";
    const source = isCount ? preset.counts : preset.points;
    input.value = source[input.dataset.type] ?? (isCount ? 0 : "");
  });
}

certSelect.addEventListener("change", applyPreset);
applyPreset();
