// VisaFlight — autocomplétion des villes/aéroports et indicatif téléphonique.
// Fichier externe (pas de script inline) pour respecter la CSP.
(function () {
  "use strict";

  // ---------- Autocomplétion ville / aéroport ----------
  function setupPlace(wrapper) {
    const input = wrapper.querySelector("[data-place-input]");
    const hidden = wrapper.querySelector("[data-place-code]");
    const list = wrapper.querySelector("[data-place-list]");
    let timer = null;
    let items = [];
    let active = -1;
    let seq = 0;

    function close() {
      list.classList.add("hidden");
      list.replaceChildren();
      active = -1;
    }

    function choose(item) {
      input.value = item.label;
      hidden.value = item.code;
      close();
    }

    function highlight(i) {
      [...list.children].forEach((li, j) => li.classList.toggle("bg-blue-50", j === i));
      active = i;
    }

    function show(results) {
      items = results;
      list.replaceChildren();
      if (!results.length) {
        const li = document.createElement("li");
        li.className = "px-3 py-2 text-sm text-slate-500";
        li.textContent = "Aucun résultat";
        list.appendChild(li);
      }
      results.forEach((item, i) => {
        const li = document.createElement("li");
        li.className = "px-3 py-2 cursor-pointer hover:bg-blue-50 flex justify-between gap-3";
        const label = document.createElement("span");
        label.textContent = item.label;
        if (item.type === "city") label.className = "font-semibold";
        const tag = document.createElement("span");
        tag.className = "text-xs text-slate-400";
        tag.textContent = item.type === "city" ? "Ville" : "Aéroport";
        li.append(label, tag);
        li.addEventListener("mousedown", (e) => { e.preventDefault(); choose(item); });
        li.addEventListener("mouseenter", () => highlight(i));
        list.appendChild(li);
      });
      list.classList.remove("hidden");
    }

    input.addEventListener("input", () => {
      hidden.value = ""; // la saisie libre invalide le choix précédent
      clearTimeout(timer);
      const q = input.value.trim();
      if (q.length < 2) { close(); return; }
      timer = setTimeout(async () => {
        const mine = ++seq;
        try {
          const r = await fetch("/api/places?q=" + encodeURIComponent(q));
          const data = r.ok ? await r.json() : [];
          if (mine === seq) show(data);
        } catch (_) { close(); }
      }, 200);
    });

    input.addEventListener("keydown", (e) => {
      if (list.classList.contains("hidden") || !items.length) return;
      if (e.key === "ArrowDown") { e.preventDefault(); highlight(Math.min(active + 1, items.length - 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); highlight(Math.max(active - 1, 0)); }
      else if (e.key === "Enter" && active >= 0) { e.preventDefault(); choose(items[active]); }
      else if (e.key === "Escape") { close(); }
    });

    input.addEventListener("blur", () => setTimeout(close, 100));
  }

  document.querySelectorAll("[data-place]").forEach(setupPlace);

  // ---------- Indicatif téléphonique selon le pays ----------
  const country = document.querySelector("[data-phone-country]");
  const phone = document.querySelector("[data-phone-number]");
  if (country && phone) {
    const dialOf = () => "+" + country.selectedOptions[0].dataset.dial;
    let currentDial = dialOf();

    function applyDial() {
      const next = dialOf();
      const value = phone.value.trim();
      if (!value || value === currentDial) {
        phone.value = next + " ";
      } else if (value.startsWith(currentDial)) {
        phone.value = next + value.slice(currentDial.length);
      } else if (!value.startsWith("+")) {
        phone.value = next + " " + value.replace(/^0+/, "");
      }
      currentDial = next;
    }

    country.addEventListener("change", () => { applyDial(); phone.focus(); });
    // Pré-remplissage à l'ouverture si le champ est vide
    if (!phone.value.trim()) phone.value = currentDial + " ";
  }
})();
