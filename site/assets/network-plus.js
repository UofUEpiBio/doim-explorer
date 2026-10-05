(() => {
  "use strict";

  // Networks +: the faculty collaboration network plus matched fellows and residents.
  //
  // This is deliberately a separate script from app.js so the original Network view is
  // untouched. It draws one published document (`doim-network-plus`), whose geometry is
  // precomputed for the full graph; when a reader narrows to some groups, the visible
  // subgraph is re-laid out here, because the full-graph coordinates leave gaps once most
  // people are hidden.

  const NETWORK_PLUS_URL = "./data/network-plus.json";
  const SCALE = 1100;
  const TRAINEE_GROUP = "fellows-residents";
  const NODE_MIN_SIZE = 7;
  const NODE_MAX_SIZE = 46;

  let doc = null;
  let promise = null;
  let cy = null;
  let pinned = null;
  let lastScope = "";
  const selected = new Set();
  let nodesById = new Map();
  let groupsById = new Map();

  const byId = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const percent = (value, total) => (total ? `${Math.round((100 * value) / total)}%` : "–");

  function safeUrl(value) {
    if (typeof value !== "string" || !value.trim()) return "";
    try {
      const url = new URL(value, window.location.href);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch (_error) {
      return "";
    }
  }

  function edgeWidth(weight) {
    return Math.min(1 + Math.sqrt(weight) * 0.9, 7);
  }

  function sizer(degrees) {
    // Cube-root scale fitted to the degrees in the current view, as on the Network view.
    const low = Math.cbrt(Math.min(1, ...degrees));
    const span = Math.cbrt(Math.max(1, ...degrees)) - low;
    return (count) => (span <= 0
      ? NODE_MIN_SIZE
      : NODE_MIN_SIZE + (NODE_MAX_SIZE - NODE_MIN_SIZE) * ((Math.cbrt(Math.max(count, 0)) - low) / span));
  }

  const isTrainee = (node) => node.kind === "trainee";

  function swatch(group, small = false, diamond = false) {
    return `<span class="network-swatch${small ? " small" : ""}${diamond ? " diamond" : ""}" style="background:${escapeHtml(group.color || "#777")};border-color:${escapeHtml(group.ring || "#444")}"></span>`;
  }

  function groupOf(node) {
    return groupsById.get(node.division_id) || {};
  }

  // ---- Loading ---------------------------------------------------------------

  async function load() {
    if (!promise) {
      promise = fetch(NETWORK_PLUS_URL, { cache: "no-cache" })
        .then((response) => {
          if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
          return response.json();
        })
        .then((value) => {
          if (value.document_type !== "doim-network-plus") throw new Error("The Networks + document has an unsupported contract.");
          doc = value;
          nodesById = new Map(doc.nodes.map((node) => [node.id, node]));
          groupsById = new Map(doc.groups.map((group) => [group.id, group]));
          render();
          return value;
        })
        .catch((error) => {
          console.warn(error);
          byId("np-count").textContent = "Networks + is not available yet.";
          byId("np-empty").hidden = false;
          return null;
        });
    }
    return promise;
  }

  function activate() {
    load().then(() => { if (cy) cy.resize(); });
  }

  // ---- Visibility ------------------------------------------------------------

  function currentFilters() {
    return {
      minWeight: Number(byId("np-weight").value || 1),
      since: Number(byId("np-since").value || 0),
    };
  }

  function nodePasses(node, filters) {
    if (selected.size && !node.groups.some((group) => selected.has(group))) return false;
    return true;
  }

  // Who is on screen: members of every chosen group (everyone if none is chosen) who still
  // have at least one link to another such member after the weight and year filters.
  function visibleParts(filters) {
    const edges = [];
    const degree = new Map();
    doc.edges.forEach((edge, index) => {
      if (edge.weight < filters.minWeight) return;
      if (filters.since && (edge.last_year || 0) < filters.since) return;
      const source = nodesById.get(edge.source);
      const target = nodesById.get(edge.target);
      if (!nodePasses(source, filters) || !nodePasses(target, filters)) return;
      edges.push(index);
      degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
    });
    return { edges: new Set(edges), degree };
  }

  // ---- Rendering -------------------------------------------------------------

  function render() {
    if (!doc || cy) return;
    if (typeof window.cytoscape !== "function") {
      byId("np-count").textContent = "Networks + needs JavaScript that did not load.";
      byId("np-empty").hidden = false;
      return;
    }
    const layoutName = byId("np-layout").value || "organic";
    const elements = [];
    doc.nodes.forEach((node) => {
      const group = groupOf(node);
      const point = (node.positions || {})[layoutName] || [0, 0];
      elements.push({
        group: "nodes",
        data: {
          id: node.id,
          name: node.name,
          kind: node.kind,
          division: node.division_id,
          groupName: group.name || node.division_id,
          color: group.color || "#777",
          ring: group.ring || "#444",
          publications: node.publications || 0,
          size: NODE_MIN_SIZE,
        },
        position: { x: point[0] * SCALE, y: point[1] * SCALE },
      });
    });
    doc.edges.forEach((edge, index) => {
      elements.push({
        group: "edges",
        data: { id: `e${index}`, index, source: edge.source, target: edge.target, weight: edge.weight, lastYear: edge.last_year || 0, width: edgeWidth(edge.weight) },
      });
    });

    const transition = reducedMotion() ? 0 : 160;
    cy = window.cytoscape({
      container: byId("np-graph"),
      elements,
      layout: { name: "preset" },
      minZoom: 0.15,
      maxZoom: 4,
      wheelSensitivity: 0.25,
      pixelRatio: window.devicePixelRatio > 1 ? 2 : 1,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            "border-color": "data(ring)",
            "border-width": 1.5,
            width: "data(size)",
            height: "data(size)",
            "transition-property": "opacity, border-width",
            "transition-duration": transition,
          },
        },
        // Fellows and residents are diamonds.
        { selector: 'node[kind != "faculty"]', style: { shape: "diamond", width: "data(size)", height: "data(size)" } },
        {
          selector: "edge",
          style: {
            "curve-style": "bezier",
            width: "data(width)",
            "line-color": "#9a9891",
            "line-opacity": 0.4,
            "transition-property": "line-opacity, line-color",
            "transition-duration": transition,
          },
        },
        { selector: "node.is-dim", style: { opacity: 0.12 } },
        { selector: "edge.is-dim", style: { "line-opacity": 0.04 } },
        { selector: ".is-hidden", style: { display: "none" } },
        { selector: "edge.is-active", style: { "line-color": "#171717", "line-opacity": 0.85, "z-index": 20 } },
        {
          selector: "node.is-active",
          style: {
            "border-width": 3,
            "border-color": "#171717",
            label: "data(name)",
            "font-size": 12,
            "font-weight": 600,
            color: "#171717",
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.92,
            "text-background-padding": 3,
            "text-background-shape": "roundrectangle",
            "text-margin-y": -6,
            "text-valign": "top",
            "z-index": 30,
          },
        },
        {
          selector: "node.is-found",
          style: {
            "border-width": 4,
            "border-color": "#be0000",
            label: "data(name)",
            "font-size": 12,
            "font-weight": 700,
            color: "#171717",
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.95,
            "text-background-padding": 3,
            "text-background-shape": "roundrectangle",
            "text-margin-y": -6,
            "text-valign": "top",
            "z-index": 40,
          },
        },
      ],
    });

    cy.on("mouseover", "node", (event) => {
      if (pinned) return;
      highlight(event.target);
      showTooltip(event.target, event.renderedPosition || event.target.renderedPosition());
    });
    cy.on("mouseout", "node", () => {
      if (pinned) return;
      byId("np-tooltip").hidden = true;
      applyFilters();
    });
    cy.on("tap", "node", (event) => {
      pinned = event.target.id();
      byId("np-tooltip").hidden = true;
      highlight(event.target);
      renderDetail(pinned);
      byId("np-reset").hidden = false;
    });
    cy.on("tap", (event) => {
      if (event.target === cy) clearSelection();
    });

    populateYears();
    renderLegend();
    renderMethod();
    renderDetail(null);
    applyFilters();
    cy.fit(cy.nodes().not(".is-hidden"), 40);
  }

  function highlight(node) {
    cy.batch(() => {
      cy.elements().addClass("is-dim").removeClass("is-active");
      const edges = node.connectedEdges().not(".is-hidden");
      node.closedNeighborhood().not(".is-hidden").removeClass("is-dim").addClass("is-active");
      edges.removeClass("is-dim").addClass("is-active");
    });
  }

  function clearSelection() {
    pinned = null;
    byId("np-reset").hidden = true;
    byId("np-tooltip").hidden = true;
    renderDetail(null);
    applyFilters();
  }

  function showTooltip(node, rendered) {
    const tooltip = byId("np-tooltip");
    const item = nodesById.get(node.id());
    const detail = isTrainee(item) ? `${escapeHtml(item.program)}` : escapeHtml(node.data("groupName"));
    tooltip.innerHTML = `<strong>${escapeHtml(item.name)}</strong><span>${item.kind === "faculty" ? "Faculty" : "Fellow/resident"} · ${detail}</span><span>${item.publications} publications</span>`;
    tooltip.hidden = false;
    const bounds = byId("np-graph").getBoundingClientRect();
    const left = Math.min(Math.max(rendered.x + 14, 8), bounds.width - tooltip.offsetWidth - 8);
    const top = Math.min(Math.max(rendered.y + 14, 8), bounds.height - tooltip.offsetHeight - 8);
    tooltip.style.transform = `translate(${left}px, ${top}px)`;
  }

  function populateYears() {
    const years = doc.edges.map((edge) => edge.last_year || 0).filter(Boolean);
    if (!years.length) return;
    const newest = Math.max(...years);
    const options = [];
    for (let year = newest; year >= newest - 10; year -= 2) options.push([String(year), `${year} or later`]);
    byId("np-since").innerHTML = '<option value="0">Any year</option>' + options
      .map(([value, label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`).join("");
  }

  function renderLegend() {
    const chips = doc.groups.map((group) => {
      const diamond = group.id === TRAINEE_GROUP;
      return `<button type="button" class="network-chip" data-group="${escapeHtml(group.id)}" aria-pressed="false">${swatch(group, false, diamond)}<span class="network-chip-name">${escapeHtml(group.name)}</span><span class="network-chip-count">${group.members}</span></button>`;
    }).join("");
    byId("np-legend").innerHTML = `<p class="network-legend-title">Show only these groups</p>${chips}`
      + `<p class="network-legend-note">Choose any number; nothing chosen shows everyone. A person with several divisions appears under each. Circles are faculty, diamonds are fellows and residents. Dot size is the number of collaborators in view; line weight is the number of shared works.</p>`;
  }

  function renderDetail(nodeId) {
    const panel = byId("np-detail");
    if (!nodeId) {
      const stats = doc.stats;
      panel.innerHTML = `<p class="network-detail-empty">Select a dot to see who that person publishes with. The full network has ${stats.faculty_nodes} faculty and ${stats.trainee_nodes} fellows and residents in ${stats.components} connected group${stats.components === 1 ? "" : "s"}.</p>`;
      return;
    }
    const node = nodesById.get(nodeId);
    if (!node) return;
    const filters = currentFilters();
    const visible = visibleParts(filters);
    const partners = [...visible.edges]
      .map((index) => doc.edges[index])
      .filter((edge) => edge.source === nodeId || edge.target === nodeId)
      .map((edge) => ({ id: edge.source === nodeId ? edge.target : edge.source, weight: edge.weight }))
      .sort((a, b) => b.weight - a.weight);
    const profile = safeUrl(node.profile_url);
    const kind = node.kind === "faculty" ? "Faculty" : node.kind === "both" ? "Faculty, also on the fellow/resident roster" : "Fellow/resident";
    const groups = node.groups.map((id) => (groupsById.get(id) || {}).name || id).join(" · ");
    const program = isTrainee(node) || node.kind === "both" ? `<p class="network-detail-stats">${escapeHtml(node.program)}${node.degree ? `, ${escapeHtml(node.degree)}` : ""}</p>` : "";
    const certainty = isTrainee(node)
      ? `<p class="network-detail-stats">Matched to publications by last name and full first name.</p>`
      : "";
    panel.innerHTML = `<div class="network-detail-head">${swatch(groupOf(node), false, node.kind !== "faculty")}<div><strong>${escapeHtml(node.name)}</strong><span>${escapeHtml(kind)}</span></div></div>`
      + `<p class="network-detail-stats">${escapeHtml(groups)}</p>${program}${certainty}`
      + `<p class="network-detail-stats">${node.publications} publications · ${partners.length} collaborators in this view</p>`
      + (profile ? `<p><a href="${escapeHtml(profile)}" target="_blank" rel="noopener noreferrer">Public profile ↗</a></p>` : "")
      + `<h4>Collaborators</h4><ul class="network-partners">`
      + partners.map((partner) => {
        const other = nodesById.get(partner.id) || {};
        return `<li><button type="button" class="network-partner" data-node="${escapeHtml(partner.id)}">${swatch(groupOf(other), true, other.kind !== "faculty")}<span class="network-partner-name">${escapeHtml(other.name || partner.id)}</span><span class="network-partner-weight">${partner.weight}</span></button></li>`;
      }).join("")
      + `</ul>`;
  }

  // ---- Filtering and layout --------------------------------------------------

  function applyFilters() {
    if (!cy || !doc) return;
    const filters = currentFilters();
    const visible = visibleParts(filters);
    const query = byId("np-query").value.trim().toLowerCase();
    const size = sizer([...visible.degree.values()]);
    cy.batch(() => {
      cy.elements().removeClass("is-dim is-active is-hidden is-found");
      cy.edges().forEach((edge) => { if (!visible.edges.has(edge.data("index"))) edge.addClass("is-hidden"); });
      cy.nodes().forEach((node) => {
        const degree = visible.degree.get(node.id());
        if (degree === undefined) node.addClass("is-hidden");
        else node.data("size", size(degree));
      });
      if (query) cy.nodes().not(".is-hidden").filter((node) => String(node.data("name")).toLowerCase().includes(query)).addClass("is-found");
    });
    updateSummary(visible);
    relayoutIfScopeChanged(visible);
    if (pinned) {
      const node = cy.getElementById(pinned);
      if (node && node.length && !node.hasClass("is-hidden")) highlight(node);
      else clearSelection();
    }
  }

  function updateSummary(visible) {
    const ids = [...visible.degree.keys()];
    const people = ids.map((id) => nodesById.get(id));
    const trainees = people.filter((node) => node.kind !== "faculty").length;
    const faculty = people.length - trainees;
    const scope = selected.size
      ? `${[...selected].map((id) => (groupsById.get(id) || {}).name || id).join(" + ")}: `
      : "";
    byId("np-count").textContent = `${scope}${people.length} people (${faculty} faculty, ${trainees} fellows/residents) · ${visible.edges.size} collaborations`;
    renderTable(visible);
  }

  function renderTable(visible) {
    const rows = [...visible.edges]
      .map((index) => doc.edges[index])
      .sort((a, b) => b.weight - a.weight || a.source.localeCompare(b.source))
      .slice(0, 25)
      .map((edge) => {
        const source = nodesById.get(edge.source) || {};
        const target = nodesById.get(edge.target) || {};
        return `<tr><td>${escapeHtml(source.name || edge.source)}</td><td>${escapeHtml(groupOf(source).name || "")}</td><td>${escapeHtml(target.name || edge.target)}</td><td>${escapeHtml(groupOf(target).name || "")}</td><td>${edge.weight}</td></tr>`;
      });
    byId("np-table").innerHTML = rows.join("");
  }

  // The published coordinates describe the whole graph. When no group is chosen, animate to
  // them (weight/year/match filters just hide people in place); when it is a subset, lay the subset out afresh so it fills the
  // canvas instead of sitting in a corner of a mostly empty one.
  function relayoutIfScopeChanged(visible) {
    const ids = [...visible.degree.keys()].sort();
    const layoutName = byId("np-layout").value || "organic";
    const scope = `${layoutName}|${ids.length}|${ids.join(",")}`;
    if (scope === lastScope) return;
    lastScope = scope;
    const everyone = selected.size === 0;
    const shown = cy.elements().not(".is-hidden");
    const duration = reducedMotion() ? 0 : 500;
    if (everyone || layoutName === "divisions") {
      cy.nodes().forEach((node) => {
        const point = (nodesById.get(node.id()).positions || {})[layoutName];
        if (!point) return;
        const target = { x: point[0] * SCALE, y: point[1] * SCALE };
        if (duration && !node.hasClass("is-hidden")) node.animate({ position: target }, { duration, easing: "ease-in-out-cubic" });
        else node.position(target);
      });
      setTimeout(() => cy.animate({ fit: { eles: cy.nodes().not(".is-hidden"), padding: 40 }, duration: duration ? 300 : 0 }), duration);
      return;
    }
    const layout = shown.layout({
      name: "cose",
      animate: duration > 0,
      animationDuration: duration,
      randomize: true,
      fit: true,
      padding: 40,
      nodeRepulsion: () => 60000,
      idealEdgeLength: () => 110,
      nodeOverlap: 40,
      numIter: 2500,
      gravity: 0.9,
      componentSpacing: 60,
    });
    // Fit once the animation has settled, so stray pairs do not leave the main body small.
    layout.one("layoutstop", () => cy.fit(cy.nodes().not(".is-hidden"), 40));
    layout.run();
  }

  function focusNode(nodeId) {
    if (!cy) return;
    const node = cy.getElementById(nodeId);
    if (!node || !node.length || node.hasClass("is-hidden")) return;
    pinned = nodeId;
    byId("np-reset").hidden = false;
    highlight(node);
    renderDetail(nodeId);
    cy.animate({ center: { eles: node }, zoom: Math.max(cy.zoom(), 1.2) }, { duration: reducedMotion() ? 0 : 400 });
  }

  // ---- Matching method and summary ------------------------------------------

  function renderMethod() {
    const { method, summary } = doc.matching;
    const sources = doc.sources;
    const scoreRow = (type, label, text) => `<tr><td>${escapeHtml(label)}</td><td>${escapeHtml(String(method.scores[type]))}</td><td>${escapeHtml(text)}</td></tr>`;
    const stale = sources.trainee_matches_publications_generated_at !== sources.publications_generated_at
      ? `<p><strong>Heads-up:</strong> the name matching was run on publications generated ${escapeHtml(sources.trainee_matches_publications_generated_at)}, but the site now holds a later set; works added since then have not been matched.</p>`
      : "";
    const stats = [
      [summary.roster, "on the 2026–27 fellow/resident roster"],
      [summary.matched_high, `matched on full first name (${percent(summary.matched_high, summary.roster)})`],
      [summary.matched_medium_only, "initial-only matches, left out"],
      [summary.unmatched, `with no publication match (${percent(summary.unmatched, summary.roster)})`],
      [summary.authorships, "authorships matched"],
      [summary.works, "distinct publications"],
    ].map(([value, label]) => `<div class="np-stat"><strong>${escapeHtml(String(value))}</strong><span>${escapeHtml(label)}</span></div>`).join("");
    const programs = (summary.by_program || []).map((row) => `<tr><td>${escapeHtml(row.program)}</td><td>${row.roster}</td><td>${row.matched_high}</td><td>${row.matched_medium_only}</td><td>${row.unmatched}</td></tr>`).join("");
    byId("np-method").innerHTML = `${stale}`
      + `<p>The department’s fellows and residents are not in the faculty directory, and the publication documents list authors by name only — no affiliation, no identifier. So each person on the program’s 2026–27 roster was matched to publication authors by name, and <strong>every match is a probability, not a fact</strong>.</p>`
      + `<h4>How a name is scored</h4>`
      + `<ol><li>The roster’s last name must equal the <em>end</em> of an author’s name, after removing accents, hyphens, apostrophes and Jr/III-type suffixes. That lets “Van Hook” or “Anderson-Bell” match however an author lists a middle name.</li>`
      + `<li>The first name is then compared with the roster first name, or with the first name in the person’s e-mail address (which sometimes differs, e.g. a nickname). Spelled-out names beat bare initials.</li></ol>`
      + `<div class="table-wrap"><table><thead><tr><th scope="col">Last name matches, and…</th><th scope="col">Score</th><th scope="col">Meaning</th></tr></thead><tbody>`
      + scoreRow("given_full", "the full first name matches", "Shown.")
      + scoreRow("given_initial", "only an initial matches (“J Raper”)", "Too ambiguous; left out.")
      + scoreRow("given_differs", "a different first name is spelled out", "Almost certainly someone else; left out.")
      + scoreRow("last_only", "the author has no given name", "Too weak; left out.")
      + `</tbody></table></div>`
      + `<p>One adjustment follows: a match is cut to ${escapeHtml(String(method.faculty_penalty))}× when the same name belongs to one of that publication’s own faculty authors, since that is more likely the faculty member. Only matches scoring at least ${escapeHtml(String(method.min_published_score))} are published here, so initial-only matches never appear. Fuzzy (near-miss) last-name matching was not used.</p>`
      + `<h4>Summary of matches</h4><div class="np-stats">${stats}</div>`
      + `<div class="table-wrap"><table><thead><tr><th scope="col">Program</th><th scope="col">Roster</th><th scope="col">Full-name match</th><th scope="col">Initial only (left out)</th><th scope="col">No match</th></tr></thead><tbody>${programs}</tbody></table></div>`
      + `<h4>What this leaves out</h4>`
      + `<p>“No match” does not mean someone has not published: the corpus holds only works attributed to a department faculty member through their own PubMed query, so a trainee’s paper with no departmental co-author is not in it at all, and many first-year residents have little published work yet. Common surnames can match the wrong person even with a first name. Matches include work done before a trainee joined the department, and a trainee who spells their name differently from the roster is missed. The roster itself is not published; only the people matched here are named.</p>`
      + `<p class="network-table-note">Matched against publications generated ${escapeHtml(sources.trainee_matches_publications_generated_at)}; the network was built ${escapeHtml(doc.generated_at)}.</p>`;
  }

  // ---- Wiring ----------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", () => {
    byId("np-filters").addEventListener("input", applyFilters);
    byId("np-reset").addEventListener("click", clearSelection);
    byId("np-legend").addEventListener("click", (event) => {
      const chip = event.target.closest("[data-group]");
      if (!chip) return;
      const id = chip.dataset.group;
      if (selected.has(id)) selected.delete(id);
      else selected.add(id);
      chip.setAttribute("aria-pressed", String(selected.has(id)));
      applyFilters();
    });
    byId("np-detail").addEventListener("click", (event) => {
      const partner = event.target.closest("[data-node]");
      if (partner) focusNode(partner.dataset.node);
    });
  });

  window.DoimNetworkPlus = { activate };
})();
