/* ============================================================
   xrypton — site interactions
   ============================================================ */
(function () {
  "use strict";

  /* ---- nav: scrolled state + mobile toggle ---- */
  const nav = document.getElementById("nav");
  const toggle = document.getElementById("navToggle");
  const links = document.getElementById("navLinks");

  const onScroll = () => {
    if (nav) nav.classList.toggle("scrolled", window.scrollY > 12);
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  if (toggle && links) {
    toggle.addEventListener("click", () => links.classList.toggle("open"));
    links.querySelectorAll("a").forEach((a) =>
      a.addEventListener("click", () => links.classList.remove("open"))
    );
  }

  /* ---- trusted-server marquee (realtime from /api/guilds) ---- */
  const trackGroups = document.querySelectorAll(".marquee-group");

  const DISCORD_CDN = "https://cdn.discordapp.com";
  const PALETTE = [
    "#7c5cff", "#36e2ff", "#ff5c8a", "#1b6bff",
    "#ffb02e", "#22c55e", "#a855f7", "#ec4899",
  ];

  const escapeHtml = (str) =>
    String(str).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  const colorFor = (id) => {
    let h = 0;
    for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return PALETTE[h % PALETTE.length];
  };

  const chipHTML = (g) => {
    const c = colorFor(g.id);
    const initial = escapeHtml((g.name || "?").trim().charAt(0).toUpperCase());
    const icon = g.icon
      ? `<img class="ic ic-img" src="${DISCORD_CDN}/icons/${g.id}/${g.icon}.png" alt="" loading="lazy" />`
      : `<span class="ic" style="background:${c}">${initial}</span>`;
    const count = g.approximate_member_count;
    const sub = Number.isFinite(count)
      ? `${count.toLocaleString()} members`
      : "Discord Server";
    return (
      `<div class="chip">${icon}` +
      `<span class="meta"><b>${escapeHtml(g.name)}</b>` +
      `<span>${sub}</span></span></div>`
    );
  };

  const fillTrack = (guilds) => {
    const html = guilds.map(chipHTML).join("");
    trackGroups.forEach((g) => (g.innerHTML = html));
  };

  /* fallback placeholder servers if the API is unavailable */
  const fallbackServers = [
    { id: "fb1", name: "Failed to get Servers", icon: null, approximate_member_count: 67 },
    { id: "fb2", name: "Failed to get Servers", icon: null, approximate_member_count: 67 },
    { id: "fb3", name: "Failed to get Servers", icon: null, approximate_member_count: 67 },
  ];

  (async () => {
    if (!trackGroups.length) return;
    try {
      const res = await fetch("/api/guilds");
      if (!res.ok) throw new Error("bad status");
      const data = await res.json();
      const guilds = Array.isArray(data) ? data : data.guilds;
      if (!guilds || !guilds.length) throw new Error("empty");
      fillTrack(guilds);
    } catch (e) {
      fillTrack(fallbackServers);
    }
  })();

  /* ---- scroll reveal ---- */
  const revealEls = document.querySelectorAll(
    ".section-head, .card, .feature, .quote, .cta, .bento, .feature-grid"
  );
  revealEls.forEach((el) => el.classList.add("reveal"));

  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    revealEls.forEach((el) => io.observe(el));
  } else {
    revealEls.forEach((el) => el.classList.add("in"));
  }

  /* ---- commands page: data + filter ---- */
  const mount = document.getElementById("cmdMount");
  const noResults = document.getElementById("noResults");
  const modal = document.getElementById("cmdModal");
  const modalTitle = document.getElementById("modalTitle");
  const modalDesc = document.getElementById("modalDesc");
  const modalArgs = document.getElementById("modalArgs");
  const modalClose = document.getElementById("modalClose");

  const closeModal = () => {
    if (modal) modal.style.display = "none";
    document.body.style.overflow = "";
  };

  if (modalClose) {
    modalClose.addEventListener("click", closeModal);
  }
  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal();
    });
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal && modal.style.display === "flex") closeModal();
  });

  const openModal = (cmd) => {
    if (!modal) return;
    modalTitle.textContent = `,${cmd.name}`;
    modalDesc.textContent = cmd.description || "No description provided.";
    modalArgs.innerHTML = "";

    if (cmd.arguments && cmd.arguments.length) {
      const table = document.createElement("div");
      table.className = "arg-table";
      cmd.arguments.forEach((arg) => {
        const row = document.createElement("div");
        row.className = "arg-row";
        row.innerHTML = `
          <span class="arg-name">${arg.name}</span>
          <span class="arg-type">${arg.type}</span>
          <span class="arg-req ${arg.required ? "req-yes" : "req-no"}">${arg.required ? "required" : `optional${arg.default !== undefined ? " (" + arg.default + ")" : ""}`}</span>
        `;
        table.appendChild(row);
      });
      modalArgs.appendChild(table);
    } else {
      modalArgs.innerHTML = `<p class="no-args">No arguments</p>`;
    }

    modal.style.display = "flex";
    document.body.style.overflow = "hidden";
  };

  if (mount) {
    const render = (categories, filter = "") => {
      const q = filter.trim().toLowerCase();
      mount.innerHTML = "";
      let total = 0;

      categories.forEach((cat) => {
        const matched = cat.commands.filter(
          (cmd) =>
            !q ||
            cmd.name.toLowerCase().includes(q) ||
            (cmd.description && cmd.description.toLowerCase().includes(q))
        );
        if (!matched.length) return;
        total += matched.length;

        const sec = document.createElement("section");
        sec.className = "cmd-group";
        sec.innerHTML = `<h3>${cat.name} <span class="tag">${matched.length} command${matched.length !== 1 ? "s" : ""}</span></h3>`;
        const list = document.createElement("div");
        list.className = "cmd-list";
        matched.forEach((cmd) => {
          const el = document.createElement("div");
          el.className = "cmd";
          el.innerHTML = `<div class="name">,${cmd.name}</div><div class="desc">${cmd.description || "No description"}</div>`;
          el.addEventListener("click", () => openModal(cmd));
          list.appendChild(el);
        });
        sec.appendChild(list);
        mount.appendChild(sec);
      });

      if (noResults) noResults.style.display = total ? "none" : "block";
    };

    (async () => {
      try {
        const res = await fetch("/api/commands");
        if (!res.ok) throw new Error("bad status");
        const data = await res.json();
        if (!data.categories || !Array.isArray(data.categories)) throw new Error("invalid");
        render(data.categories);
      } catch (e) {
        mount.innerHTML = `<p style="color:var(--muted)">Failed to load commands. Please try again later.</p>`;
        if (noResults) noResults.style.display = "none";
      }
    })();

    const input = document.getElementById("cmdSearch");
    if (input) {
      input.addEventListener("input", async (e) => {
        const q = e.target.value;
        try {
          const res = await fetch("/api/commands");
          if (!res.ok) throw new Error("bad status");
          const data = await res.json();
          if (!data.categories || !Array.isArray(data.categories)) throw new Error("invalid");
          render(data.categories, q);
        } catch (err) {
          // keep previous render on filter error
        }
      });
    }
  }
})();
