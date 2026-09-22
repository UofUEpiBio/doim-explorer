(() => {
  "use strict";

  const BRANDING_URL = "./data/branding.json";
  const DIRECTORY_URL = "./data/directory.json";
  const PUBLICATIONS_URL = "./data/publications.json";
  const PUBLICATION_DETAILS_URL = "./data/publication-details.json";
  const COLLABORATION_URL = "./data/collaboration.json";
  const VIEWS = ["ask", "overview", "faculty", "expertise", "publications", "network", "health"];
  const ASK_URL = "https://doim-ask-d4mznpfqta-uc.a.run.app/ask";
  const ASK_MARKER = /\[\[[^\]\s]{1,64}\]\]/g;
  const ASK_FRAME_MS = 80;

  let directory = null;
  let branding = null;
  let publications = { works: [], health: [] };
  let publicationDetails = null;
  let detailsPromise = null;
  let divisionsById = new Map();
  let facultyById = new Map();
  let publicationsById = new Map();
  let askController = null;
  let askFrame = 0;
  let collaboration = null;
  let collaborationPromise = null;
  let cy = null;
  let networkDivision = "";
  let networkPinned = null;

  const byId = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

  function safeUrl(value) {
    if (typeof value !== "string" || !value.trim()) return "";
    try {
      const url = new URL(value, window.location.href);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch (_error) {
      return "";
    }
  }

  function formatDate(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? "Date not supplied"
      : new Intl.DateTimeFormat("en", { dateStyle: "medium" }).format(date);
  }

  function siteAssetUrl(name) {
    if (typeof name !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._-]*\.(ico|png|svg|webp)$/.test(name)) return "";
    return new URL(`./assets/${name}`, window.location.href).href;
  }

  function loadAnalytics(measurementId) {
    if (!/^G-[A-Z0-9]{6,20}$/.test(measurementId) || document.querySelector("script[data-doim-analytics]")) return;
    const script = document.createElement("script");
    script.async = true;
    script.dataset.doimAnalytics = "true";
    script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(measurementId)}`;
    document.head.append(script);
    window.dataLayer = window.dataLayer || [];
    window.gtag = window.gtag || function gtag() { window.dataLayer.push(arguments); };
    window.gtag("js", new Date());
    window.gtag("config", measurementId);
  }

  function applyBranding(value) {
    if (value.document_type !== "doim-branding") throw new Error("The branding document has an unsupported contract.");
    branding = value;
    const { site, theme, assets, analytics } = branding;
    document.title = site.title;
    byId("brand-title").textContent = site.title;
    byId("brand-subtitle").textContent = site.subtitle;
    byId("official-site-link").href = site.official_url;
    byId("footer-official-link").href = site.official_url;
    byId("footer-official-link").textContent = site.official_name;
    byId("unofficial-notice").textContent = site.unofficial_notice;
    byId("og-title").content = site.title;
    byId("og-description").content = `${site.unofficial_notice} ${site.subtitle}`;
    Object.entries(theme).forEach(([name, color]) => {
      document.documentElement.style.setProperty(`--brand-${name.replace("_", "-")}`, color);
    });
    const socialCard = siteAssetUrl(assets.social_card);
    byId("og-image").content = socialCard;
    const favicon = siteAssetUrl(assets.favicon);
    if (favicon) byId("site-favicon").href = favicon;
    const mark = siteAssetUrl(assets.mark);
    if (mark) {
      byId("brand-mark").src = mark;
      byId("brand-mark").alt = `${site.title} mark`;
      byId("brand-mark").hidden = false;
    }
    loadAnalytics(analytics.measurement_id || "");
  }

  function divisionName(id) {
    return divisionsById.get(id)?.name || "Unassigned division";
  }

  function tags(values = []) {
    return values.length
      ? `<div class="tag-list">${values.slice(0, 8).map((value) => `<span class="tag">${escapeHtml(value)}</span>`).join("")}</div>`
      : "";
  }

  function facultyText(faculty) {
    return [
      faculty.full_name,
      faculty.title,
      faculty.bio,
      faculty.academic_information,
      ...(faculty.division_ids || []).map(divisionName),
    ].filter(Boolean).join(" ").toLowerCase();
  }

  function publicationText(publication) {
    return [
      publication.title,
      publication.venue,
      ...(publication.keywords || []),
      ...(publication.faculty_ids || []).map((id) => facultyById.get(id)?.full_name),
    ].filter(Boolean).join(" ").toLowerCase();
  }

  function divisionCard(division) {
    const facultyCount = (directory.faculty || []).filter((faculty) => faculty.division_ids?.includes(division.id)).length;
    const sourceUrl = safeUrl(division.source_url);
    const facultyUrl = safeUrl(division.faculty_url);
    return `<article class="card researcher-card">
      <p class="card-meta">Division</p>
      <h3>${sourceUrl ? `<a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(division.name)}</a>` : escapeHtml(division.name)}</h3>
      ${division.summary ? `<p>${escapeHtml(division.summary)}</p>` : ""}
      <div class="card-footer"><span class="card-meta">${facultyCount} collected faculty profile${facultyCount === 1 ? "" : "s"}</span>${facultyUrl ? `<a href="${escapeHtml(facultyUrl)}" target="_blank" rel="noopener noreferrer">Faculty directory ↗</a>` : ""}</div>
    </article>`;
  }

  function facultyCard(faculty) {
    const profileUrl = safeUrl(faculty.profile_url);
    const orcidUrl = faculty.orcid_id ? `https://orcid.org/${encodeURIComponent(faculty.orcid_id)}` : "";
    return `<article class="card researcher-card">
      <p class="card-meta">${escapeHtml((faculty.division_ids || []).map(divisionName).join(" · "))}</p>
      <h3>${profileUrl ? `<a href="${escapeHtml(profileUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(faculty.full_name)}</a>` : escapeHtml(faculty.full_name)}</h3>
      ${faculty.title ? `<p class="researcher-role">${escapeHtml(faculty.title)}</p>` : ""}
      ${faculty.bio ? `<p>${escapeHtml(faculty.bio)}</p>` : ""}
      ${tags(faculty.expertise || [])}
      <div class="card-footer">${orcidUrl ? `<a href="${escapeHtml(orcidUrl)}" target="_blank" rel="noopener noreferrer">ORCID ↗</a>` : ""}</div>
    </article>`;
  }

  function publicationCard(publication) {
    const url = safeUrl(publication.url);
    const faculty = (publication.faculty_ids || []).map((id) => facultyById.get(id)?.full_name || id).join(", ");
    const abstract = publicationDetails?.details?.[publication.id]?.abstract;
    return `<article class="work-card">
      <div class="work-topline"><span>${escapeHtml(publication.type || "publication")}</span><span>${escapeHtml(formatDate(publication.published_at))}</span></div>
      <h3>${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(publication.title)}</a>` : escapeHtml(publication.title)}</h3>
      ${publication.venue ? `<p class="work-venue">${escapeHtml(publication.venue)}</p>` : ""}
      ${faculty ? `<p class="work-authors">${escapeHtml(faculty)}</p>` : ""}
      ${tags(publication.keywords || [])}
      ${abstract ? `<details><summary>Abstract</summary><p>${escapeHtml(abstract)}</p></details>` : publication.has_abstract ? '<button class="text-action" type="button" data-load-details="true">Load abstract</button>' : ""}
    </article>`;
  }

  function populateSelect(id, values) {
    byId(id).insertAdjacentHTML("beforeend", values.map(([value, text]) => `<option value="${escapeHtml(value)}">${escapeHtml(text)}</option>`).join(""));
  }

  function renderOverview() {
    byId("division-list").innerHTML = directory.divisions.length
      ? directory.divisions.map(divisionCard).join("")
      : '<div class="empty-state compact"><h3>No divisions published yet.</h3></div>';
  }

  function renderFaculty() {
    const query = byId("faculty-query").value.trim().toLowerCase();
    const division = byId("faculty-division").value;
    const matches = (directory.faculty || []).filter((faculty) =>
      (!division || faculty.division_ids?.includes(division)) && (!query || facultyText(faculty).includes(query)),
    );
    byId("faculty-count").textContent = `${matches.length} faculty profile${matches.length === 1 ? "" : "s"}`;
    byId("faculty-list").innerHTML = matches.length
      ? matches.map(facultyCard).join("")
      : '<div class="empty-state compact"><h3>No matching faculty profiles.</h3><p>Faculty profiles will appear after the public directory collection runs.</p></div>';
  }

  function renderPublications() {
    const query = byId("publication-query").value.trim().toLowerCase();
    const division = byId("publication-division").value;
    const faculty = byId("publication-faculty").value;
    const matches = (publications.works || []).filter((publication) =>
      (!division || publication.division_ids?.includes(division)) &&
      (!faculty || publication.faculty_ids?.includes(faculty)) &&
      (!query || publicationText(publication).includes(query)),
    );
    byId("publication-count").textContent = `${matches.length} publication${matches.length === 1 ? "" : "s"}`;
    byId("publication-list").innerHTML = matches.length
      ? matches.map(publicationCard).join("")
      : '<div class="empty-state compact"><h3>No publications match.</h3><p>Publication records will appear after faculty collection and scholarly metadata refreshes run.</p></div>';
  }

  function search(query, targetSummary, targetResults) {
    const term = query.trim().toLowerCase();
    if (!term) {
      byId(targetSummary).textContent = "Enter a topic, name, or method to search the public directory.";
      byId(targetResults).innerHTML = "";
      return;
    }
    const faculty = (directory.faculty || []).filter((record) => facultyText(record).includes(term));
    const publicationsFound = (publications.works || []).filter((record) => publicationText(record).includes(term));
    byId(targetSummary).textContent = `${faculty.length} faculty match${faculty.length === 1 ? "" : "es"}; ${publicationsFound.length} publication match${publicationsFound.length === 1 ? "" : "es"}.`;
    byId(targetResults).innerHTML = `${faculty.length ? `<section class="expert-group"><h3>Faculty <span class="count-pill">${faculty.length}</span></h3><div class="researcher-grid">${faculty.map(facultyCard).join("")}</div></section>` : ""}${publicationsFound.length ? `<section class="expert-group"><h3>Publications <span class="count-pill">${publicationsFound.length}</span></h3><div class="works-list">${publicationsFound.map(publicationCard).join("")}</div></section>` : ""}${!faculty.length && !publicationsFound.length ? '<div class="empty-state compact"><h3>No matching records.</h3><p>Try a broader term or check the official department site.</p></div>' : ""}`;
  }

  // Assisted answers come from the separately deployed DOIM Ask service, which indexes the
  // same published documents this page loads, so every record it cites is shown here too.
  function askEndpoint() {
    // A local override keeps the deployed endpoint out of development, and is limited to
    // https or localhost so a stray value cannot redirect questions somewhere hostile.
    let override = "";
    try {
      override = window.localStorage.getItem("doim-ask-url") || "";
    } catch (_error) {
      override = "";
    }
    const url = safeUrl(override || ASK_URL);
    if (!url) return "";
    return url.startsWith("https://") || url.startsWith("http://localhost") ? url : "";
  }

  function setAskStatus(text) { byId("ask-status").textContent = text; }

  function showAskNotice(text) {
    const notice = byId("ask-notice");
    notice.textContent = text;
    notice.hidden = !text;
  }

  // Every failure lands here: rate limited, over budget, offline, or not deployed. The
  // reader still gets the keyword search this page can run alone, so Ask is never a dead end.
  function askFallback(query, notice) {
    showAskNotice(notice);
    setAskStatus("Showing keyword matches instead.");
    search(query, "ask-summary", "ask-results");
    byId("ask-fallback").hidden = false;
  }

  function askCitationCard(entry) {
    // A cited publication or faculty member is rendered by the card the rest of the site
    // uses, so its links are identical wherever a reader meets it.
    const publication = entry.work_id ? publicationsById.get(entry.work_id) : null;
    if (publication) return publicationCard(publication);
    const faculty = entry.kind === "researcher" ? facultyById.get(String(entry.id).slice(2)) : null;
    if (faculty) return facultyCard(faculty);
    const division = entry.kind === "center" ? divisionsById.get(String(entry.id).slice(2)) : null;
    if (division) return divisionCard(division);
    const url = safeUrl(entry.url);
    const title = escapeHtml(entry.title || "Untitled");
    const detail = [entry.subtitle, entry.venue, entry.year].filter(Boolean).map((part) => escapeHtml(String(part))).join(" · ");
    return `<article class="card ask-citation"><h4>${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${title}</a>` : title}</h4>${detail ? `<p class="result-count">${detail}</p>` : ""}</article>`;
  }

  function renderAskCitations(citations) {
    const cards = citations.map(askCitationCard).join("");
    byId("ask-citations").innerHTML = cards ? `<h3 class="ask-citations-heading">Sources</h3>${cards}` : "";
  }

  // Retrieval offers the model far more documents than it ends up citing, so numbering by
  // position in that list produces footnotes that start at 7 and jump around. These are
  // numbered by order of first appearance, and only the cited ones are listed.
  function citedInOrder(text, citations) {
    return citations
      .map((entry) => ({ entry, at: text.indexOf(`[[${entry.id}]]`) }))
      .filter((item) => item.at !== -1)
      .sort((a, b) => a.at - b.at)
      .map((item) => item.entry);
  }

  function renderAskAnswer(text, citations) {
    const cited = citedInOrder(text, citations);
    let html = escapeHtml(text);
    cited.forEach((entry, position) => {
      const url = safeUrl(entry.url);
      const number = position + 1;
      const label = url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${number}</a>` : String(number);
      // Literal substitution over the ids the service actually offered. Nothing is parsed
      // out of the model's text, so a marker it invented cannot become a link.
      html = html.replaceAll(`[[${entry.id}]]`, `<sup class="ask-cite">${label}</sup>`);
    });
    html = html.replace(ASK_MARKER, "");
    renderAskCitations(cited);
    byId("ask-answer").innerHTML = html.split(/\n{2,}/).map((paragraph) => paragraph.trim()).filter(Boolean).map((paragraph) => `<p>${paragraph}</p>`).join("");
  }

  async function readAskStream(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let split = buffer.indexOf("\n\n");
      while (split !== -1) {
        const frame = buffer.slice(0, split);
        buffer = buffer.slice(split + 2);
        const name = frame.match(/^event: (.*)$/m)?.[1] || "";
        const data = frame.match(/^data: (.*)$/m)?.[1] || "{}";
        try {
          onEvent(name, JSON.parse(data));
        } catch (_error) {
          // A frame that arrives malformed is skipped rather than ending the answer.
        }
        split = buffer.indexOf("\n\n");
      }
    }
  }

  function noticeFor(detail, status) {
    if (detail.error === "rate_limited") return "That is a lot of questions at once. Showing keyword matches instead.";
    if (detail.error === "budget_exhausted") return "The assistant has reached its monthly budget. Showing keyword matches instead.";
    return `The assistant is unavailable right now (${status}).`;
  }

  async function askQuestion(query) {
    const question = String(query || "").trim();
    if (!question) return;
    askController?.abort();
    askController = new AbortController();

    byId("ask-query").value = question;
    byId("ask-echo").textContent = `\u201c${question}\u201d`;
    byId("ask-error").hidden = true;
    byId("ask-answer").innerHTML = "";
    byId("ask-answer-sr").textContent = "";
    byId("ask-citations").innerHTML = "";
    byId("ask-fallback").hidden = true;
    showAskNotice("");
    showView("ask");

    if (question.length > 300) {
      const error = byId("ask-error");
      error.textContent = "Please shorten the question to 300 characters or fewer.";
      error.hidden = false;
      return;
    }

    const endpoint = askEndpoint();
    if (!endpoint) {
      askFallback(question, "The assisted answer service is not configured yet.");
      return;
    }

    setAskStatus("Thinking\u2026");
    byId("ask-answer").setAttribute("aria-busy", "true");
    let citations = [];
    let answer = "";
    let refused = false;

    const paint = () => { askFrame = 0; renderAskAnswer(answer, citations); };
    const schedule = () => { if (!askFrame) askFrame = window.setTimeout(paint, ASK_FRAME_MS); };

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question }),
        signal: askController.signal,
      });
      if (!response.ok || !response.body) {
        const detail = await response.json().catch(() => ({}));
        if (response.status === 400 || response.status === 422) {
          const error = byId("ask-error");
          error.textContent = detail.detail || "That question could not be read.";
          error.hidden = false;
          setAskStatus("");
          return;
        }
        // The service returns a no-answer as a normal 200, so anything else means the
        // assistant is unavailable rather than merely unsure.
        askFallback(question, noticeFor(detail, response.status));
        return;
      }
      await readAskStream(response, (name, payload) => {
        if (name === "meta") {
          // Sources arrive before the prose and stay client-side, so a citation never
          // costs a second request; they appear as the answer cites them.
          citations = payload.citations || [];
          setAskStatus("Reading the department\u2019s record\u2026");
        } else if (name === "token") {
          answer += payload.t || "";
          schedule();
        } else if (name === "no_match" || name === "error") {
          refused = true;
        }
      });
    } catch (error) {
      if (error.name === "AbortError") return;
      askFallback(question, "The assisted answer could not be reached.");
      return;
    } finally {
      byId("ask-answer").setAttribute("aria-busy", "false");
      window.clearTimeout(askFrame);
      askFrame = 0;
    }

    if (refused || !answer.trim()) {
      // A stream can fail after some prose has already painted, which an exhausted upstream
      // quota does exactly. Half a sentence above "showing keyword matches instead" reads
      // like a broken page, so it is cleared rather than left.
      byId("ask-answer").innerHTML = "";
      byId("ask-answer-sr").textContent = "";
      byId("ask-citations").innerHTML = "";
      askFallback(question, "That question could not be answered from this department\u2019s published records.");
      return;
    }
    paint();
    // Count what the answer actually cites, not everything retrieval offered the model.
    const cited = citedInOrder(answer, citations).length;
    setAskStatus(`Answer ready${cited ? ` \u00b7 ${cited} source${cited === 1 ? "" : "s"}` : ""}.`);
    // Screen readers cannot follow a region that mutates on every frame, so the finished
    // answer is announced once here instead.
    byId("ask-answer-sr").textContent = answer.trim();
  }

  function renderHealth() {
    const health = [...(directory.health || []), ...(publications.health || [])];
    byId("last-updated").textContent = `Directory updated ${formatDate(directory.generated_at)}`;
    byId("health-empty").hidden = health.length > 0;
    byId("health-body").innerHTML = health.map((record) => `<tr><td>${escapeHtml(record.division_id ? divisionName(record.division_id) : "—")}</td><td>${escapeHtml(record.source_label || record.source || record.source_type || "Source")}</td><td><span class="status-badge status-${escapeHtml(record.status || "pending")}">${escapeHtml(record.status || "pending")}</span></td><td>${escapeHtml(record.message || "")}</td></tr>`).join("");
  }

  function renderMetrics() {
    const health = [...(directory.health || []), ...(publications.health || [])];
    byId("metric-divisions").textContent = directory.stats?.divisions ?? directory.divisions.length;
    byId("metric-faculty").textContent = directory.stats?.faculty ?? directory.faculty.length;
    byId("metric-publications").textContent = publications.stats?.works ?? publications.works.length;
    byId("metric-sources").textContent = health.length;
    byId("footer-generated").textContent = `Directory generated ${formatDate(directory.generated_at)}`;
    byId("freshness").classList.add("is-current");
    byId("freshness").lastElementChild.textContent = `Directory updated ${formatDate(directory.generated_at)}`;
  }


  // ---- Collaboration network ---------------------------------------------------
  // The published document carries its own geometry, so this view never runs a layout:
  // it draws precomputed coordinates and animates between the two of them.

  const NETWORK_SCALE = 1100;
  const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function nodeSize(publicationCount) {
    return 10 + Math.sqrt(Math.max(publicationCount, 0)) * 2.6;
  }

  function edgeWidth(weight) {
    return Math.min(1 + Math.sqrt(weight) * 0.9, 7);
  }

  function loadCollaboration() {
    if (!collaborationPromise) {
      collaborationPromise = fetchJson(COLLABORATION_URL)
        .then((value) => {
          if (value.document_type !== "doim-collaboration") throw new Error("The collaboration document has an unsupported contract.");
          collaboration = value;
          renderNetwork();
          return value;
        })
        .catch((error) => {
          console.warn(error);
          byId("network-count").textContent = "The collaboration network is not available yet.";
          byId("network-empty").hidden = false;
          return null;
        });
    }
    return collaborationPromise;
  }

  function renderNetwork() {
    if (!collaboration || cy) return;
    if (typeof window.cytoscape !== "function") {
      byId("network-count").textContent = "The collaboration network needs JavaScript that did not load.";
      byId("network-empty").hidden = false;
      return;
    }
    const palette = new Map((collaboration.divisions || []).map((division) => [division.id, division]));
    const layout = byId("network-layout").value || "organic";
    const elements = [];
    (collaboration.nodes || []).forEach((node) => {
      const division = palette.get(node.division_id) || {};
      const point = (node.positions || {})[layout] || [0, 0];
      elements.push({
        group: "nodes",
        data: {
          id: node.id,
          name: node.name,
          division: node.division_id,
          divisionName: division.name || node.division_id,
          color: division.color || "#777",
          ring: division.ring || "#444",
          profile: node.profile_url || "",
          publications: node.publications || 0,
          collaborators: node.collaborators || 0,
          size: nodeSize(node.publications || 0),
        },
        position: { x: point[0] * NETWORK_SCALE, y: point[1] * NETWORK_SCALE },
      });
    });
    (collaboration.edges || []).forEach((edge, index) => {
      elements.push({
        group: "edges",
        data: {
          id: `e${index}`,
          source: edge.source,
          target: edge.target,
          weight: edge.weight,
          lastYear: edge.last_year || 0,
          width: edgeWidth(edge.weight),
        },
      });
    });

    cy = window.cytoscape({
      container: byId("network-graph"),
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
            "transition-duration": reducedMotion() ? 0 : 160,
          },
        },
        {
          selector: "edge",
          style: {
            "curve-style": "bezier",
            width: "data(width)",
            "line-color": "#9a9891",
            "line-opacity": 0.4,
            "transition-property": "line-opacity, line-color",
            "transition-duration": reducedMotion() ? 0 : 160,
          },
        },
        { selector: "node.is-dim", style: { opacity: 0.12 } },
        { selector: "edge.is-dim", style: { "line-opacity": 0.04 } },
        { selector: "node.is-hidden", style: { opacity: 0.05 } },
        { selector: "edge.is-hidden", style: { display: "none" } },
        {
          selector: "edge.is-active",
          style: { "line-color": "data(color)", "line-opacity": 0.85, "z-index": 20 },
        },
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
      if (networkPinned) return;
      highlightNode(event.target);
      showNetworkTooltip(event.target, event.renderedPosition || event.target.renderedPosition());
    });
    cy.on("mouseout", "node", () => {
      if (networkPinned) return;
      hideNetworkTooltip();
      applyNetworkFilters();
    });
    cy.on("tap", "node", (event) => {
      networkPinned = event.target.id();
      hideNetworkTooltip();
      highlightNode(event.target);
      renderNetworkDetail(event.target.id());
      byId("network-reset").hidden = false;
    });
    cy.on("tap", (event) => {
      if (event.target === cy) clearNetworkSelection();
    });

    populateNetworkYears();
    renderNetworkLegend();
    renderNetworkTable();
    renderNetworkDetail(null);
    applyNetworkFilters();
    cy.fit(undefined, 40);
  }

  function highlightNode(node) {
    const neighborhood = node.closedNeighborhood();
    cy.batch(() => {
      cy.elements().addClass("is-dim").removeClass("is-active");
      neighborhood.removeClass("is-dim").addClass("is-active");
      node.connectedEdges().removeClass("is-dim").addClass("is-active");
    });
  }

  function clearNetworkSelection() {
    networkPinned = null;
    byId("network-reset").hidden = true;
    hideNetworkTooltip();
    renderNetworkDetail(null);
    applyNetworkFilters();
  }

  function showNetworkTooltip(node, rendered) {
    const tooltip = byId("network-tooltip");
    tooltip.innerHTML = `<strong>${escapeHtml(node.data("name"))}</strong><span>${escapeHtml(node.data("divisionName"))}</span><span>${node.data("collaborators")} collaborators · ${node.data("publications")} publications</span>`;
    tooltip.hidden = false;
    const bounds = byId("network-graph").getBoundingClientRect();
    const left = Math.min(Math.max(rendered.x + 14, 8), bounds.width - tooltip.offsetWidth - 8);
    const top = Math.min(Math.max(rendered.y + 14, 8), bounds.height - tooltip.offsetHeight - 8);
    tooltip.style.transform = `translate(${left}px, ${top}px)`;
  }

  function hideNetworkTooltip() {
    byId("network-tooltip").hidden = true;
  }

  function populateNetworkYears() {
    const years = (collaboration.edges || []).map((edge) => edge.last_year || 0).filter(Boolean);
    if (!years.length) return;
    const newest = Math.max(...years);
    const options = [];
    for (let year = newest; year >= newest - 10; year -= 2) options.push([String(year), `${year} or later`]);
    const select = byId("network-since");
    select.innerHTML = '<option value="0">Any year</option>' + options
      .map(([value, label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`).join("");
  }

  function renderNetworkLegend() {
    const stats = collaboration.stats || {};
    byId("network-legend").innerHTML = `<p class="network-legend-title">Divisions</p>` + (collaboration.divisions || [])
      .map((division) => `<button type="button" class="network-chip" data-division="${escapeHtml(division.id)}" aria-pressed="false"><span class="network-swatch" style="background:${escapeHtml(division.color)};border-color:${escapeHtml(division.ring)}"></span><span class="network-chip-name">${escapeHtml(division.name)}</span><span class="network-chip-count">${division.faculty}</span></button>`)
      .join("") + `<p class="network-legend-note">Dot size is that faculty member’s publication count. Line weight is the number of works two people share.</p>`;
    byId("network-count").textContent = `${stats.nodes} faculty · ${stats.edges} collaborations · ${stats.cross_division_edges} of them across divisions`;
  }

  function renderNetworkTable() {
    const byIdMap = new Map((collaboration.nodes || []).map((node) => [node.id, node]));
    const divisions = new Map((collaboration.divisions || []).map((division) => [division.id, division.name]));
    const rows = [...(collaboration.edges || [])]
      .sort((a, b) => b.weight - a.weight || a.source.localeCompare(b.source))
      .slice(0, 25)
      .map((edge) => {
        const source = byIdMap.get(edge.source) || {};
        const target = byIdMap.get(edge.target) || {};
        return `<tr><td>${escapeHtml(source.name || edge.source)}</td><td>${escapeHtml(divisions.get(source.division_id) || "")}</td><td>${escapeHtml(target.name || edge.target)}</td><td>${escapeHtml(divisions.get(target.division_id) || "")}</td><td>${edge.weight}</td></tr>`;
      });
    byId("network-table").innerHTML = rows.join("");
  }

  function renderNetworkDetail(nodeId) {
    const panel = byId("network-detail");
    if (!nodeId) {
      const stats = collaboration.stats || {};
      panel.innerHTML = `<p class="network-detail-empty">Select a dot to see who that faculty member publishes with. The largest connected group holds ${stats.largest_component} of the ${stats.nodes} faculty shown.</p>`;
      return;
    }
    const node = (collaboration.nodes || []).find((item) => item.id === nodeId);
    if (!node) return;
    const divisions = new Map((collaboration.divisions || []).map((division) => [division.id, division]));
    const division = divisions.get(node.division_id) || {};
    const partners = (collaboration.edges || [])
      .filter((edge) => edge.source === nodeId || edge.target === nodeId)
      .map((edge) => ({ id: edge.source === nodeId ? edge.target : edge.source, weight: edge.weight, lastYear: edge.last_year }))
      .sort((a, b) => b.weight - a.weight);
    const nodesById = new Map((collaboration.nodes || []).map((item) => [item.id, item]));
    const profile = safeUrl(node.profile_url);
    panel.innerHTML = `<div class="network-detail-head"><span class="network-swatch" style="background:${escapeHtml(division.color || "#777")};border-color:${escapeHtml(division.ring || "#444")}"></span><div><strong>${escapeHtml(node.name)}</strong><span>${escapeHtml(division.name || node.division_id)}</span></div></div>`
      + `<p class="network-detail-stats">${node.publications} publications · ${node.collaborators} departmental collaborators · ${node.shared_works} co-authored works</p>`
      + (profile ? `<p><a href="${escapeHtml(profile)}" target="_blank" rel="noopener noreferrer">Public profile ↗</a></p>` : "")
      + `<h4>Collaborators</h4><ul class="network-partners">`
      + partners.map((partner) => {
        const other = nodesById.get(partner.id) || {};
        const otherDivision = divisions.get(other.division_id) || {};
        return `<li><button type="button" class="network-partner" data-node="${escapeHtml(partner.id)}"><span class="network-swatch small" style="background:${escapeHtml(otherDivision.color || "#777")};border-color:${escapeHtml(otherDivision.ring || "#444")}"></span><span class="network-partner-name">${escapeHtml(other.name || partner.id)}</span><span class="network-partner-weight">${partner.weight}</span></button></li>`;
      }).join("")
      + `</ul>`;
  }

  function applyNetworkFilters() {
    if (!cy) return;
    const minWeight = Number(byId("network-weight").value || 1);
    const since = Number(byId("network-since").value || 0);
    const query = byId("network-query").value.trim().toLowerCase();
    cy.batch(() => {
      cy.elements().removeClass("is-dim is-active is-hidden is-found");
      const hiddenEdges = cy.edges().filter((edge) => edge.data("weight") < minWeight || (since && edge.data("lastYear") < since));
      hiddenEdges.addClass("is-hidden");
      const visibleEdges = cy.edges().not(hiddenEdges);
      const connected = visibleEdges.connectedNodes();
      cy.nodes().not(connected).addClass("is-hidden");
      if (networkDivision) {
        cy.nodes().filter((node) => node.data("division") !== networkDivision).addClass("is-dim");
        visibleEdges.filter((edge) => edge.source().data("division") !== networkDivision && edge.target().data("division") !== networkDivision).addClass("is-dim");
      }
      if (query) {
        const found = cy.nodes().filter((node) => String(node.data("name")).toLowerCase().includes(query));
        found.addClass("is-found");
      }
    });
    if (networkPinned) {
      const node = cy.getElementById(networkPinned);
      if (node && node.length) highlightNode(node);
    }
  }

  function setNetworkLayout(name) {
    if (!cy || !collaboration) return;
    const positions = new Map((collaboration.nodes || []).map((node) => [node.id, (node.positions || {})[name]]));
    const duration = reducedMotion() ? 0 : 700;
    cy.nodes().forEach((node) => {
      const point = positions.get(node.id());
      if (!point) return;
      const target = { x: point[0] * NETWORK_SCALE, y: point[1] * NETWORK_SCALE };
      if (duration) node.animate({ position: target }, { duration, easing: "ease-in-out-cubic" });
      else node.position(target);
    });
    setTimeout(() => cy.animate({ fit: { padding: 40 }, duration: duration ? 300 : 0 }), duration);
  }

  function focusNetworkNode(nodeId) {
    if (!cy) return;
    const node = cy.getElementById(nodeId);
    if (!node || !node.length) return;
    networkPinned = nodeId;
    byId("network-reset").hidden = false;
    highlightNode(node);
    renderNetworkDetail(nodeId);
    cy.animate({ center: { eles: node }, zoom: Math.max(cy.zoom(), 1.2) }, { duration: reducedMotion() ? 0 : 400 });
  }

  function showView(view) {
    const active = VIEWS.includes(view) ? view : "ask";
    document.querySelectorAll("[data-view-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.viewPanel !== active;
      panel.classList.toggle("is-active", panel.dataset.viewPanel === active);
    });
    document.querySelectorAll("[data-view]").forEach((button) => button.classList.toggle("is-active", button.dataset.view === active));
    history.replaceState(null, "", `#${active}`);
    // The network document and its renderer are only worth fetching once a reader asks
    // for them, and cytoscape needs its container to be visible before it can size itself.
    if (active === "network") loadCollaboration().then(() => { if (cy) cy.resize(); });
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-cache" });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  }

  function loadPublicationDetails() {
    if (!detailsPromise) {
      detailsPromise = fetchJson(PUBLICATION_DETAILS_URL)
        .then((value) => { publicationDetails = value; renderPublications(); return value; })
        .catch(() => null);
    }
    return detailsPromise;
  }

  async function initialize() {
    try {
      applyBranding(await fetchJson(BRANDING_URL));
    } catch (error) {
      console.warn("Branding could not be loaded; using the built-in fallback.", error);
    }
    try {
      directory = await fetchJson(DIRECTORY_URL);
      if (directory.document_type !== "doim-directory") throw new Error("The directory document has an unsupported contract.");
      divisionsById = new Map((directory.divisions || []).map((division) => [division.id, division]));
      facultyById = new Map((directory.faculty || []).map((faculty) => [faculty.id, faculty]));
      byId("department-title").textContent = directory.department?.name || "University of Utah Department of Internal Medicine";
      byId("department-description").textContent = directory.department?.summary || "Explore the department’s divisions, faculty expertise, and public publications.";
      populateSelect("faculty-division", directory.divisions.map((division) => [division.id, division.name]));
      populateSelect("publication-division", directory.divisions.map((division) => [division.id, division.name]));
      populateSelect("publication-faculty", (directory.faculty || []).map((faculty) => [faculty.id, faculty.full_name]));
      renderOverview(); renderFaculty(); renderMetrics(); renderHealth();
      try {
        const value = await fetchJson(PUBLICATIONS_URL);
        if (value.document_type !== "doim-publications") throw new Error("The publications document has an unsupported contract.");
        publications = value;
        publicationsById = new Map((publications.works || []).map((work) => [work.id, work]));
        renderMetrics(); renderPublications(); renderHealth();
      } catch (error) {
        byId("publication-count").textContent = "Publications are not available yet.";
        console.warn(error);
      }
      showView(window.location.hash.slice(1));
    } catch (error) {
      byId("app-message").hidden = false;
      byId("app-message").textContent = `The DOIM directory could not be loaded: ${error.message}. Run doim-directory to publish it.`;
      byId("freshness").classList.add("is-stale");
      byId("freshness").lastElementChild.textContent = "Directory unavailable";
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
    window.addEventListener("hashchange", () => showView(window.location.hash.slice(1)));
    byId("faculty-filters").addEventListener("input", renderFaculty);
    byId("publication-filters").addEventListener("input", renderPublications);
    byId("expertise-form").addEventListener("submit", (event) => { event.preventDefault(); search(byId("expertise-query").value, "expertise-summary", "expertise-results"); });
    byId("ask-form").addEventListener("submit", (event) => { event.preventDefault(); askQuestion(byId("ask-query").value); });
    byId("network-filters").addEventListener("input", (event) => {
      if (event.target.id === "network-layout") setNetworkLayout(event.target.value);
      else applyNetworkFilters();
    });
    byId("network-reset").addEventListener("click", clearNetworkSelection);
    byId("network-legend").addEventListener("click", (event) => {
      const chip = event.target.closest("[data-division]");
      if (!chip) return;
      networkDivision = networkDivision === chip.dataset.division ? "" : chip.dataset.division;
      byId("network-legend").querySelectorAll("[data-division]").forEach((button) => {
        button.setAttribute("aria-pressed", String(button.dataset.division === networkDivision));
      });
      applyNetworkFilters();
    });
    byId("network-detail").addEventListener("click", (event) => {
      const partner = event.target.closest("[data-node]");
      if (partner) focusNetworkNode(partner.dataset.node);
    });
    document.addEventListener("click", (event) => { if (event.target.matches("[data-load-details]")) loadPublicationDetails(); });
    initialize();
  });
})();
