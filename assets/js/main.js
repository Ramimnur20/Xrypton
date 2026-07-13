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
  const cmdData = [
    {
      group: "Moderation",
      desc: "Keep your server clean and in order.",
      cmds: [
        ["ban", "Ban a member from the server."],
        ["kick", "Kick a member from the server."],
        ["timeout", "Temporarily mute a member."],
        ["warn", "Warn a member and track strikes."],
        ["clear", "Bulk delete messages in a channel."],
        ["lock", "Lock a channel from sending messages."],
        ["unlock", "Unlock a previously locked channel."],
        ["slowmode", "Set channel slowmode duration."],
      ],
    },
    {
      group: "Anti-Nuke",
      desc: "Automatic protection against malicious attacks.",
      cmds: [
        ["antinuke enable", "Enable anti-nuke protection for the server."],
        ["antinuke config", "Configure thresholds and actions."],
        ["whitelist", "Whitelist roles or members from checks."],
        ["punishment", "Set the punishment for detected nukes."],
      ],
    },
    {
      group: "Anti-Raid",
      desc: "Stop coordinated raids before they start.",
      cmds: [
        ["antiraid enable", "Turn on anti-raid detection."],
        ["raid lock", "Lock the server during an active raid."],
        ["raid config", "Tune join-rate and account-age filters."],
      ],
    },
    {
      group: "VoiceMaster",
      desc: "Temporary, personalized voice channels.",
      cmds: [
        ["voicemaster setup", "Create the Join-to-Create system."],
        ["voicemaster claim", "Claim an inactive voice channel."],
        ["voicemaster name", "Rename your voice channel."],
        ["voicemaster lock", "Lock your voice channel."],
        ["voicemaster unlock", "Unlock your voice channel."],
        ["voicemaster ghost", "Hide your voice channel."],
        ["voicemaster reveal", "Reveal your voice channel."],
        ["voicemaster limit", "Set the user limit."],
        ["voicemaster bitrate", "Change channel audio quality."],
        ["voicemaster transfer", "Transfer ownership to another member."],
        ["voicemaster permit", "Allow a member or role to join."],
        ["voicemaster reject", "Remove a member from your channel."],
      ],
    },
    {
      group: "Economy",
      desc: "A full virtual currency system.",
      cmds: [
        ["balance", "View your wallet and bank."],
        ["daily", "Claim your daily reward."],
        ["work", "Work a job to earn cash."],
        ["rob", "Attempt to rob another member."],
        ["shop", "Browse the server shop."],
        ["buy", "Purchase an item from the shop."],
        ["leaderboard", "See the richest members."],
        ["give", "Transfer money to another member."],
      ],
    },
    {
      group: "Levels",
      desc: "Reward activity with ranking.",
      cmds: [
        ["rank", "View your or another member's rank."],
        ["leaderboard levels", "Top ranked members."],
        ["level rewards", "Configure role rewards."],
      ],
    },
    {
      group: "Giveaway",
      desc: "Host giveaways in seconds.",
      cmds: [
        ["giveaway start", "Start a new giveaway."],
        ["giveaway end", "End a giveaway early."],
        ["giveaway reroll", "Reroll the winner."],
      ],
    },
    {
      group: "Tickets",
      desc: "Private, moderated support.",
      cmds: [
        ["ticket setup", "Create a ticket panel."],
        ["ticket open", "Open a support ticket."],
        ["ticket close", "Close the current ticket."],
        ["ticket add", "Add a member to the ticket."],
      ],
    },
    {
      group: "Snipe",
      desc: "Recover deleted and edited content.",
      cmds: [
        ["snipe", "View the last deleted message."],
        ["editsnipe", "View the last edited message."],
        ["reactionsnipe", "View the last removed reaction."],
      ],
    },
    {
      group: "Fun & Games",
      desc: "Keep your community entertained.",
      cmds: [
        ["tictactoe", "Play tic-tac-toe with a friend."],
        ["blackjack", "Play a round of blackjack."],
        ["meme", "Fetch a random meme."],
        ["tts", "Convert text to speech."],
        ["8ball", "Ask the magic 8-ball."],
        ["translate", "Translate text to another language."],
      ],
    },
    {
      group: "Information",
      desc: "Quick server and member stats.",
      cmds: [
        ["userinfo", "Detailed info about a member."],
        ["serverinfo", "Detailed info about the server."],
        ["avatar", "View a member's avatar."],
        ["ping", "Check the bot's latency."],
      ],
    },
    {
      group: "Miscellaneous",
      desc: "Handy utilities for any server.",
      cmds: [
        ["prefix", "Change the server command prefix."],
        ["poll", "Create a quick poll."],
        ["remind", "Set a personal reminder."],
        ["embed", "Send a custom embed message."],
        ["say", "Make the bot repeat a message."],
      ],
    },
  ];

  const mount = document.getElementById("cmdMount");
  if (mount) {
    const render = (filter = "") => {
      const q = filter.trim().toLowerCase();
      mount.innerHTML = "";
      let total = 0;

      cmdData.forEach((cat) => {
        const matched = cat.cmds.filter(
          ([name, d]) =>
            !q || name.toLowerCase().includes(q) || d.toLowerCase().includes(q)
        );
        if (!matched.length) return;
        total += matched.length;

        const sec = document.createElement("section");
        sec.className = "cmd-group";
        sec.innerHTML =
          `<h3>${cat.group} <span class="tag">${cat.desc}</span></h3>`;
        const list = document.createElement("div");
        list.className = "cmd-list";
        matched.forEach(([name, d]) => {
          const el = document.createElement("div");
          el.className = "cmd";
          el.innerHTML = `<div class="name">,${name}</div><div class="desc">${d}</div>`;
          list.appendChild(el);
        });
        sec.appendChild(list);
        mount.appendChild(sec);
      });

      const none = document.getElementById("noResults");
      if (none) none.style.display = total ? "none" : "block";
    };

    render();

    const input = document.getElementById("cmdSearch");
    if (input) input.addEventListener("input", (e) => render(e.target.value));
  }
})();
