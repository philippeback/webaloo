/**
 * Webaloo Frontend Controller
 * Implements Symbaloo-style 2D grid drag & swap, context menu, tile/mix modals,
 * icon discovery, global instant search (Ctrl+K / '/'), and SSE live disk sync.
 */
const Webaloo = (() => {
  let draggedTile = null;
  let justDragged = false;
  let draggedTabSlug = null;
  let contextTileId = null;
  let urlFetchTimer = null;
  let searchResults = [];
  let searchSelectedIndex = 0;
  let deferredReload = false;
  let sseSource = null;

  function getActiveMixData() {
    const el = document.getElementById("active-mix-data");
    if (!el) return { slug: "default", title: "Default", grid_cols: 12, grid_rows: 8, tiles: [] };
    try {
      return JSON.parse(el.textContent);
    } catch {
      return { slug: "default", title: "Default", grid_cols: 12, grid_rows: 8, tiles: [] };
    }
  }

  function getAllMixesData() {
    const el = document.getElementById("all-mixes-data");
    if (!el) return [];
    try {
      return JSON.parse(el.textContent);
    } catch {
      return [];
    }
  }

  function getTileData(tileId) {
    const el = document.getElementById(`tile-data-${tileId}`);
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch {
      return null;
    }
  }

  function isAnyModalOpen() {
    const modals = ["tile-modal", "mix-modal", "search-modal"];
    return modals.some((id) => {
      const el = document.getElementById(id);
      return el && !el.classList.contains("hidden");
    });
  }

  function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    if (!container) return;
    const toast = document.createElement("div");
    const colorClass =
      type === "error"
        ? "bg-rose-950/95 border-rose-500/60 text-rose-200"
        : type === "success"
        ? "bg-emerald-950/95 border-emerald-500/60 text-emerald-200"
        : "bg-slate-900/95 border-slate-700 text-slate-200";
    toast.className = `pointer-events-auto px-4 py-2.5 rounded-xl border shadow-xl text-xs font-medium transition-all duration-200 ${colorClass}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      setTimeout(() => toast.remove(), 220);
    }, 3200);
  }

  function refreshIcons() {
    if (window.lucide && typeof window.lucide.createIcons === "function") {
      window.lucide.createIcons();
    }
  }

  async function refreshActiveWorkspace(mixSlug = null, highlightTile = null) {
    const targetSlug = mixSlug || getActiveMixData().slug;
    const url = highlightTile
      ? `/mix/${encodeURIComponent(targetSlug)}?highlight=${encodeURIComponent(highlightTile)}`
      : `/mix/${encodeURIComponent(targetSlug)}`;
    if (window.htmx) {
      await window.htmx.ajax("GET", url, { target: "#workspace-root", swap: "innerHTML" });
      if (mixSlug) {
        window.history.pushState({}, "", `/mix/${encodeURIComponent(targetSlug)}`);
      }
      refreshIcons();
    } else {
      window.location.href = url;
    }
  }

  // --- Drag & Drop Tiles on Fixed 2D Grid (REQ-GRID-004, REQ-GRID-005, REQ-GRID-006) ---
  function onTileDragStart(event, tileId, x, y) {
    hideContextMenu();
    draggedTile = { tileId, fromX: x, fromY: y };
    justDragged = true;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", tileId);
    const slot = event.currentTarget;
    setTimeout(() => slot.classList.add("dragging-source"), 10);
  }

  function onSlotDragOver(event, x, y) {
    if (!draggedTile) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    event.currentTarget.classList.add("drag-over-target");
  }

  function onSlotDragLeave(event) {
    event.currentTarget.classList.remove("drag-over-target");
  }

  async function onSlotDrop(event, targetX, targetY) {
    event.preventDefault();
    event.currentTarget.classList.remove("drag-over-target");
    if (!draggedTile) return;

    const { tileId, fromX, fromY } = draggedTile;
    draggedTile = null;
    if (fromX === targetX && fromY === targetY) return;

    const mix = getActiveMixData();
    try {
      const resp = await fetch(
        `/api/mixes/${encodeURIComponent(mix.slug)}/tiles/${encodeURIComponent(tileId)}/move`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ x: targetX, y: targetY }),
        }
      );
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to move tile");
      }
      await refreshActiveWorkspace(mix.slug);
    } catch (err) {
      showToast(err.message || "Move failed; reverting tile position.", "error");
      await refreshActiveWorkspace(mix.slug);
    }
  }

  function onTileDragEnd(event) {
    event.currentTarget.classList.remove("dragging-source");
    document.querySelectorAll(".drag-over-target").forEach((el) => el.classList.remove("drag-over-target"));
    setTimeout(() => {
      justDragged = false;
    }, 120);
  }

  function onTileClick(event) {
    if (justDragged) {
      event.preventDefault();
      return false;
    }
    return true;
  }

  // --- Drag & Drop Webmix Tabs (REQ-MIX-005) ---
  function onTabDragStart(event, slug) {
    draggedTabSlug = slug;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", slug);
  }

  function onTabDragOver(event) {
    if (!draggedTabSlug) return;
    event.preventDefault();
    event.currentTarget.classList.add("tab-drag-over");
  }

  async function onTabDrop(event, targetSlug) {
    event.preventDefault();
    event.currentTarget.classList.remove("tab-drag-over");
    if (!draggedTabSlug || draggedTabSlug === targetSlug) return;

    const tabElements = Array.from(document.querySelectorAll("#webmix-tabs .mix-tab-item"));
    const slugs = tabElements.map((el) => el.getAttribute("data-mix-slug"));
    const fromIdx = slugs.indexOf(draggedTabSlug);
    const toIdx = slugs.indexOf(targetSlug);
    if (fromIdx === -1 || toIdx === -1) return;

    slugs.splice(fromIdx, 1);
    slugs.splice(toIdx, 0, draggedTabSlug);
    draggedTabSlug = null;

    try {
      const resp = await fetch("/api/mixes/reorder", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ order: slugs }),
      });
      if (!resp.ok) throw new Error("Failed to reorder tabs");
      await refreshActiveWorkspace();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  function onTabDragEnd() {
    draggedTabSlug = null;
    document.querySelectorAll(".tab-drag-over").forEach((el) => el.classList.remove("tab-drag-over"));
  }

  // --- Right-Click & Hover Context Menu (REQ-TILE-006..011) ---
  function onTileContextMenu(event, tileId) {
    event.preventDefault();
    event.stopPropagation();
    showContextMenu(event.clientX, event.clientY, tileId);
  }

  function onTileMenuButton(event, tileId) {
    event.preventDefault();
    event.stopPropagation();
    const rect = event.currentTarget.getBoundingClientRect();
    showContextMenu(rect.left, rect.bottom + 4, tileId);
  }

  function showContextMenu(x, y, tileId) {
    contextTileId = tileId;
    const menu = document.getElementById("tile-context-menu");
    const submenu = document.getElementById("ctx-move-submenu");
    if (!menu || !submenu) return;

    const activeMix = getActiveMixData();
    const mixes = getAllMixesData().filter((m) => m.slug !== activeMix.slug);
    if (mixes.length === 0) {
      submenu.innerHTML = `<div class="px-3 py-1.5 text-xs text-slate-500">No other webmixes</div>`;
    } else {
      submenu.innerHTML = mixes
        .map(
          (m) =>
            `<button type="button" onclick="Webaloo.ctxTransferTile('${m.slug}')"
                     class="w-full px-3.5 py-1.5 text-left text-xs hover:bg-indigo-600/30 hover:text-white truncate block">
               ${m.title}
             </button>`
        )
        .join("");
    }

    menu.classList.remove("hidden");
    const maxX = window.innerWidth - 220;
    const maxY = window.innerHeight - 190;
    menu.style.left = `${Math.max(8, Math.min(x, maxX))}px`;
    menu.style.top = `${Math.max(8, Math.min(y, maxY))}px`;
    refreshIcons();
  }

  function hideContextMenu() {
    const menu = document.getElementById("tile-context-menu");
    if (menu) menu.classList.add("hidden");
  }

  function ctxEditTile() {
    const tileId = contextTileId;
    hideContextMenu();
    if (tileId) openEditTileModal(tileId);
  }

  async function ctxDuplicateTile() {
    const tileId = contextTileId;
    hideContextMenu();
    if (!tileId) return;
    const mix = getActiveMixData();
    try {
      const resp = await fetch(
        `/api/mixes/${encodeURIComponent(mix.slug)}/tiles/${encodeURIComponent(tileId)}/duplicate`,
        { method: "POST" }
      );
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || "Could not duplicate tile");
      }
      showToast("Tile duplicated", "success");
      await refreshActiveWorkspace(mix.slug);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function ctxTransferTile(targetMixSlug) {
    const tileId = contextTileId;
    hideContextMenu();
    if (!tileId || !targetMixSlug) return;
    const mix = getActiveMixData();
    try {
      const resp = await fetch(
        `/api/mixes/${encodeURIComponent(mix.slug)}/tiles/${encodeURIComponent(tileId)}/transfer`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target_mix: targetMixSlug }),
        }
      );
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to move tile to webmix");
      }
      showToast(`Moved tile to '${targetMixSlug}'`, "success");
      await refreshActiveWorkspace(mix.slug);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function ctxDeleteTile() {
    const tileId = contextTileId;
    hideContextMenu();
    if (!tileId) return;
    const mix = getActiveMixData();
    try {
      const resp = await fetch(
        `/api/mixes/${encodeURIComponent(mix.slug)}/tiles/${encodeURIComponent(tileId)}`,
        { method: "DELETE" }
      );
      if (!resp.ok) throw new Error("Failed to delete tile");
      showToast("Tile deleted", "info");
      await refreshActiveWorkspace(mix.slug);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  // --- Tile Create / Edit Modal & Icon System (REQ-TILE-003..007, REQ-ICON-002..006) ---
  function openCreateTileModal(x = 0, y = 0) {
    hideContextMenu();
    document.getElementById("tile-modal-title").textContent = `Create Tile at (${x}, ${y})`;
    document.getElementById("tile-form-mode").value = "create";
    document.getElementById("tile-form-id").value = "";
    document.getElementById("tile-url").value = "";
    document.getElementById("tile-name").value = "";
    document.getElementById("tile-target").value = "_blank";
    document.getElementById("tile-x").value = x;
    document.getElementById("tile-y").value = y;
    document.getElementById("tile-cached-url").value = "";
    document.getElementById("tile-lucide-name").value = "globe";
    document.getElementById("tile-external-url").value = "";
    document.getElementById("tile-monogram").value = "";
    setTileBgColor("#1e293b");
    setTileTextColor("#ffffff");
    document.getElementById("tile-show-label").checked = true;
    document.getElementById("tile-tags").value = "";
    document.getElementById("icon-fetch-status").classList.add("hidden");

    setIconMode("monogram");
    updateTilePreview();
    document.getElementById("tile-modal").classList.remove("hidden");
    setTimeout(() => document.getElementById("tile-url").focus(), 50);
  }

  function openEditTileModal(tileId) {
    const tile = getTileData(tileId);
    if (!tile) return;

    document.getElementById("tile-modal-title").textContent = `Edit Tile — ${tile.name}`;
    document.getElementById("tile-form-mode").value = "edit";
    document.getElementById("tile-form-id").value = tile.id;
    document.getElementById("tile-url").value = tile.url || "";
    document.getElementById("tile-name").value = tile.name || "";
    document.getElementById("tile-target").value = tile.target || "_blank";
    document.getElementById("tile-x").value = tile.x;
    document.getElementById("tile-y").value = tile.y;
    document.getElementById("tile-cached-url").value =
      tile.icon_type === "cached" ? tile.icon_url || "" : "";
    document.getElementById("tile-lucide-name").value = tile.icon || "globe";
    document.getElementById("tile-external-url").value =
      tile.icon_type === "external" ? tile.icon_url || "" : "";
    document.getElementById("tile-monogram").value = tile.monogram || "";
    setTileBgColor(tile.bg_color || "#1e293b");
    setTileTextColor(tile.text_color || "#ffffff");
    document.getElementById("tile-show-label").checked = tile.show_label !== false;
    document.getElementById("tile-tags").value = (tile.tags || []).join(", ");
    document.getElementById("icon-fetch-status").classList.add("hidden");

    setIconMode(tile.icon_type || "monogram");
    updateTilePreview();
    document.getElementById("tile-modal").classList.remove("hidden");
  }

  function closeTileModal() {
    document.getElementById("tile-modal").classList.add("hidden");
    checkFlushDeferredReload();
  }

  function setTileBgColor(hex) {
    document.getElementById("tile-bg-color").value = hex;
    if (/^#[0-9a-fA-F]{6}$/.test(hex)) {
      document.getElementById("tile-bg-picker").value = hex;
    }
    updateTilePreview();
  }

  function setTileTextColor(hex) {
    document.getElementById("tile-text-color").value = hex;
    if (/^#[0-9a-fA-F]{6}$/.test(hex)) {
      document.getElementById("tile-text-picker").value = hex;
    }
    updateTilePreview();
  }

  function setIconMode(mode) {
    document.getElementById("tile-icon-type").value = mode;
    document.querySelectorAll(".icon-mode-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-icon-tab") === mode);
    });
    ["cached", "lucide", "external", "monogram"].forEach((m) => {
      const panel = document.getElementById(`icon-panel-${m}`);
      if (panel) panel.classList.toggle("hidden", m !== mode);
    });
    updateTilePreview();
  }

  function selectLucideIcon(iconName) {
    document.getElementById("tile-lucide-name").value = iconName;
    setIconMode("lucide");
  }

  function filterLucideIcons(query) {
    const q = (query || "").trim().toLowerCase();
    document.querySelectorAll("#lucide-picker-grid .lucide-option").forEach((btn) => {
      const name = btn.getAttribute("data-lucide-option") || "";
      btn.classList.toggle("hidden", q !== "" && !name.includes(q));
    });
  }

  function computeMonogram(name, url) {
    const clean = (name || "").trim();
    if (clean) {
      const words = clean.split(/[\s\-_/]+/).filter(Boolean);
      if (words.length >= 2) {
        return words
          .slice(0, 3)
          .map((w) => w[0])
          .join("")
          .toUpperCase();
      }
      return clean.slice(0, 2).toUpperCase();
    }
    if (url) {
      const host = url.replace(/^https?:\/\/(www\.)?/i, "").split("/")[0];
      return (host.slice(0, 2) || "WB").toUpperCase();
    }
    return "WB";
  }

  function updateTilePreview() {
    const name = document.getElementById("tile-name").value.trim() || "Bookmark";
    const url = document.getElementById("tile-url").value.trim();
    const x = document.getElementById("tile-x").value || 0;
    const y = document.getElementById("tile-y").value || 0;
    const bgColor = document.getElementById("tile-bg-color").value.trim() || "#1e293b";
    const textColor = document.getElementById("tile-text-color").value.trim() || "#ffffff";
    const showLabel = document.getElementById("tile-show-label").checked;
    const iconType = document.getElementById("tile-icon-type").value;
    const monogram =
      document.getElementById("tile-monogram").value.trim().toUpperCase() ||
      computeMonogram(name, url);

    const previewBox = document.getElementById("tile-live-preview");
    const previewIcon = document.getElementById("tile-preview-icon");
    const previewLabel = document.getElementById("tile-preview-label");
    const coordsBadge = document.getElementById("tile-coords-badge");

    previewBox.style.backgroundColor = bgColor;
    previewBox.style.color = textColor;
    coordsBadge.textContent = `Slot (${x}, ${y})`;

    previewLabel.textContent = name;
    previewLabel.classList.toggle("hidden", !showLabel);

    if (iconType === "cached") {
      const cachedUrl = document.getElementById("tile-cached-url").value.trim();
      if (cachedUrl) {
        previewIcon.innerHTML = `<img src="${cachedUrl}" class="w-9 h-9 object-contain rounded" alt="icon" />`;
      } else {
        previewIcon.innerHTML = `<span class="font-bold text-xl uppercase">${monogram}</span>`;
      }
    } else if (iconType === "external") {
      const extUrl = document.getElementById("tile-external-url").value.trim();
      if (extUrl) {
        previewIcon.innerHTML = `<img src="${extUrl}" class="w-9 h-9 object-contain rounded" alt="icon" />`;
      } else {
        previewIcon.innerHTML = `<span class="font-bold text-xl uppercase">${monogram}</span>`;
      }
    } else if (iconType === "lucide") {
      const lucideName = document.getElementById("tile-lucide-name").value.trim() || "globe";
      previewIcon.innerHTML = `<i data-lucide="${lucideName}" class="w-8 h-8"></i>`;
      refreshIcons();
    } else {
      previewIcon.innerHTML = `<span class="font-bold text-xl uppercase">${monogram}</span>`;
    }
  }

  function onTileUrlInput(value) {
    updateTilePreview();
    if (urlFetchTimer) clearTimeout(urlFetchTimer);
    const trimmed = (value || "").trim();
    if (/^https?:\/\/[^/\s]+\.[^/\s]+/i.test(trimmed)) {
      urlFetchTimer = setTimeout(() => {
        fetchSiteMetadata();
      }, 650);
    }
  }

  async function fetchSiteMetadata() {
    const url = document.getElementById("tile-url").value.trim();
    if (!url) return;
    const statusEl = document.getElementById("icon-fetch-status");
    statusEl.textContent = "Discovering page title & high-res icon...";
    statusEl.classList.remove("hidden");

    try {
      const resp = await fetch("/api/icons/fetch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const data = await resp.json();
      const nameInput = document.getElementById("tile-name");
      if (!nameInput.value.trim() && data.title) {
        nameInput.value = data.title;
      }
      if (data.monogram && !document.getElementById("tile-monogram").value.trim()) {
        document.getElementById("tile-monogram").value = data.monogram;
      }
      if (data.ok && data.icon_url) {
        document.getElementById("tile-cached-url").value = data.icon_url;
        setIconMode("cached");
        statusEl.textContent = `Cached site icon: ${data.icon_url}`;
      } else {
        setIconMode("monogram");
        statusEl.textContent = "No remote icon found — using styled monogram badge.";
      }
      updateTilePreview();
    } catch {
      statusEl.textContent = "Offline / unreachable — using monogram fallback.";
      setIconMode("monogram");
    }
  }

  async function uploadCustomIcon(fileInput) {
    if (!fileInput.files || fileInput.files.length === 0) return;
    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append("file", file);

    try {
      const resp = await fetch("/api/icons/upload", {
        method: "POST",
        body: formData,
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Upload failed");
      document.getElementById("tile-cached-url").value = data.icon_url;
      setIconMode("cached");
      showToast(`Uploaded ${data.filename}`, "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function submitTileForm(event) {
    event.preventDefault();
    const mix = getActiveMixData();
    const mode = document.getElementById("tile-form-mode").value;
    const tileId = document.getElementById("tile-form-id").value;
    const iconType = document.getElementById("tile-icon-type").value;

    let iconUrl = null;
    if (iconType === "cached") {
      iconUrl = document.getElementById("tile-cached-url").value.trim() || null;
    } else if (iconType === "external") {
      iconUrl = document.getElementById("tile-external-url").value.trim() || null;
    }

    const payload = {
      name: document.getElementById("tile-name").value.trim(),
      url: document.getElementById("tile-url").value.trim(),
      target: document.getElementById("tile-target").value,
      x: parseInt(document.getElementById("tile-x").value, 10),
      y: parseInt(document.getElementById("tile-y").value, 10),
      bg_color: document.getElementById("tile-bg-color").value.trim(),
      text_color: document.getElementById("tile-text-color").value.trim(),
      show_label: document.getElementById("tile-show-label").checked,
      icon_type: iconType,
      icon: iconType === "lucide" ? document.getElementById("tile-lucide-name").value.trim() : null,
      icon_url: iconUrl,
      monogram: document.getElementById("tile-monogram").value.trim() || null,
      tags: document
        .getElementById("tile-tags")
        .value.split(",")
        .map((t) => t.trim())
        .filter(Boolean),
    };

    try {
      const endpoint =
        mode === "edit"
          ? `/api/mixes/${encodeURIComponent(mix.slug)}/tiles/${encodeURIComponent(tileId)}`
          : `/api/mixes/${encodeURIComponent(mix.slug)}/tiles`;
      const method = mode === "edit" ? "PUT" : "POST";
      const resp = await fetch(endpoint, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to save tile");
      }
      closeTileModal();
      showToast(mode === "edit" ? "Tile updated" : "Tile created", "success");
      await refreshActiveWorkspace(mix.slug);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  // --- Create / Edit Webmix Modal (REQ-MIX-003..008) ---
  function openCreateMixModal() {
    document.getElementById("mix-modal-title").textContent = "Create New Webmix";
    document.getElementById("mix-form-mode").value = "create";
    document.getElementById("mix-form-slug").value = "";
    document.getElementById("mix-title").value = "";
    document.getElementById("mix-custom-slug").value = "";
    document.getElementById("mix-slug-field").classList.remove("hidden");
    document.getElementById("mix-cols").value = 12;
    document.getElementById("mix-rows").value = 8;
    document.getElementById("mix-theme").value = "dark";
    document.getElementById("mix-background").value = "#0f172a";
    document.getElementById("mix-bounds-warning").classList.add("hidden");
    document.getElementById("mix-relocate-checkbox").checked = false;
    document.getElementById("btn-delete-mix").classList.add("hidden");

    document.getElementById("mix-modal").classList.remove("hidden");
    setTimeout(() => document.getElementById("mix-title").focus(), 50);
  }

  function openEditMixModal() {
    const mix = getActiveMixData();
    document.getElementById("mix-modal-title").textContent = `Edit Webmix — ${mix.title}`;
    document.getElementById("mix-form-mode").value = "edit";
    document.getElementById("mix-form-slug").value = mix.slug;
    document.getElementById("mix-title").value = mix.title;
    document.getElementById("mix-slug-field").classList.add("hidden");
    document.getElementById("mix-cols").value = mix.grid_cols;
    document.getElementById("mix-rows").value = mix.grid_rows;
    document.getElementById("mix-theme").value = mix.theme || "dark";
    document.getElementById("mix-background").value = mix.background || "#0f172a";
    document.getElementById("mix-bounds-warning").classList.add("hidden");
    document.getElementById("mix-relocate-checkbox").checked = false;
    document.getElementById("btn-delete-mix").classList.remove("hidden");

    document.getElementById("mix-modal").classList.remove("hidden");
  }

  function closeMixModal() {
    document.getElementById("mix-modal").classList.add("hidden");
    checkFlushDeferredReload();
  }

  function checkMixBoundsWarning() {
    const mode = document.getElementById("mix-form-mode").value;
    const warningEl = document.getElementById("mix-bounds-warning");
    if (mode !== "edit") {
      warningEl.classList.add("hidden");
      return;
    }
    const mix = getActiveMixData();
    const newCols = parseInt(document.getElementById("mix-cols").value, 10) || mix.grid_cols;
    const newRows = parseInt(document.getElementById("mix-rows").value, 10) || mix.grid_rows;
    const outOfBounds = (mix.tiles || []).filter((t) => t.x >= newCols || t.y >= newRows);
    if (outOfBounds.length > 0) {
      const names = outOfBounds.map((t) => `${t.name} (${t.x},${t.y})`).join(", ");
      document.getElementById(
        "mix-bounds-warning-text"
      ).textContent = `${outOfBounds.length} tile(s) lie outside ${newCols}×${newRows}: ${names}`;
      warningEl.classList.remove("hidden");
    } else {
      warningEl.classList.add("hidden");
    }
  }

  async function submitMixForm(event) {
    event.preventDefault();
    const mode = document.getElementById("mix-form-mode").value;
    const slug = document.getElementById("mix-form-slug").value;

    const payload = {
      title: document.getElementById("mix-title").value.trim(),
      slug: document.getElementById("mix-custom-slug").value.trim() || undefined,
      grid_cols: parseInt(document.getElementById("mix-cols").value, 10),
      grid_rows: parseInt(document.getElementById("mix-rows").value, 10),
      theme: document.getElementById("mix-theme").value,
      background: document.getElementById("mix-background").value.trim(),
      relocate_out_of_bounds: document.getElementById("mix-relocate-checkbox").checked,
    };

    try {
      const endpoint = mode === "edit" ? `/api/mixes/${encodeURIComponent(slug)}` : "/api/mixes";
      const method = mode === "edit" ? "PUT" : "POST";
      const resp = await fetch(endpoint, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.status === 409 && data.code === "OUT_OF_BOUNDS_TILES") {
        checkMixBoundsWarning();
        showToast("Please check 'Automatically relocate out-of-bounds tiles' to shrink grid.", "error");
        return;
      }
      if (!resp.ok) {
        throw new Error(data.detail || "Failed to save webmix");
      }
      closeMixModal();
      showToast(mode === "edit" ? "Webmix updated" : "Webmix created", "success");
      await refreshActiveWorkspace(data.slug || slug);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function confirmDeleteActiveMix() {
    const mix = getActiveMixData();
    if (!window.confirm(`Delete webmix '${mix.title}' and all its tiles?`)) return;
    try {
      const resp = await fetch(`/api/mixes/${encodeURIComponent(mix.slug)}`, { method: "DELETE" });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Failed to delete webmix");
      closeMixModal();
      showToast(`Deleted webmix '${mix.title}'`, "info");
      await refreshActiveWorkspace(data.next_mix || "default");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  // --- Global Instant Search Command Palette (REQ-SRCH-001..003) ---
  async function openSearchModal() {
    hideContextMenu();
    const modal = document.getElementById("search-modal");
    const input = document.getElementById("global-search-input");
    modal.classList.remove("hidden");
    input.value = "";
    input.focus();
    await onSearchInput("");
  }

  function closeSearchModal() {
    document.getElementById("search-modal").classList.add("hidden");
    checkFlushDeferredReload();
  }

  async function onSearchInput(query) {
    try {
      const resp = await fetch(`/api/search?q=${encodeURIComponent(query || "")}`);
      const data = await resp.json();
      searchResults = data.results || [];
      searchSelectedIndex = 0;
      renderSearchResults();
    } catch {
      searchResults = [];
      renderSearchResults();
    }
  }

  function renderSearchResults() {
    const listEl = document.getElementById("search-results-list");
    const countEl = document.getElementById("search-count-label");
    countEl.textContent = `${searchResults.length} tile${searchResults.length === 1 ? "" : "s"}`;

    if (searchResults.length === 0) {
      listEl.innerHTML = `<div class="p-6 text-center text-xs text-slate-500">No matching tiles found.</div>`;
      return;
    }

    listEl.innerHTML = searchResults
      .map((item, idx) => {
        const isSel = idx === searchSelectedIndex;
        const tagsHtml = (item.tags || [])
          .map((t) => `<span class="px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 text-[10px]">#${t}</span>`)
          .join(" ");
        return `
          <div class="px-4 py-2.5 flex items-center justify-between gap-3 cursor-pointer transition ${
            isSel ? "bg-indigo-600/25 text-white" : "hover:bg-slate-800/60 text-slate-300"
          }"
               onclick="Webaloo.activateSearchResult(${idx}, false)"
               onmouseenter="Webaloo.setSearchIndex(${idx})">
            <div class="flex items-center gap-3 min-w-0">
              <div class="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 font-bold text-xs border border-white/10"
                   style="background-color: ${item.bg_color}; color: ${item.text_color};">
                ${item.monogram || "WB"}
              </div>
              <div class="min-w-0">
                <div class="text-xs font-semibold truncate flex items-center gap-2">
                  <span>${item.name}</span>
                  ${tagsHtml}
                </div>
                <div class="text-[11px] text-slate-400 truncate">${item.url}</div>
              </div>
            </div>
            <div class="shrink-0 flex items-center gap-2">
              <span class="px-2 py-0.5 rounded-md bg-slate-800 border border-slate-700 text-[11px] text-indigo-300 font-medium">
                ${item.mix_title} (${item.x},${item.y})
              </span>
            </div>
          </div>
        `;
      })
      .join("");
  }

  function setSearchIndex(idx) {
    searchSelectedIndex = idx;
    renderSearchResults();
  }

  async function activateSearchResult(idx, jumpToMix = false) {
    const item = searchResults[idx];
    if (!item) return;
    closeSearchModal();
    if (jumpToMix) {
      await refreshActiveWorkspace(item.mix_slug, item.tile_id);
    } else {
      window.open(item.url, item.target || "_blank", "noopener,noreferrer");
    }
  }

  function onSearchKeyDown(event) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (searchResults.length > 0) {
        searchSelectedIndex = (searchSelectedIndex + 1) % searchResults.length;
        renderSearchResults();
      }
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (searchResults.length > 0) {
        searchSelectedIndex = (searchSelectedIndex - 1 + searchResults.length) % searchResults.length;
        renderSearchResults();
      }
    } else if (event.key === "Enter") {
      event.preventDefault();
      activateSearchResult(searchSelectedIndex, event.altKey);
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeSearchModal();
    }
  }

  // --- Live External File Sync via SSE (REQ-SYNC-003, REQ-SYNC-004) ---
  function initSSE() {
    if (sseSource) sseSource.close();
    sseSource = new EventSource("/api/events");
    sseSource.addEventListener("reload", async () => {
      if (isAnyModalOpen()) {
        deferredReload = true;
        const badge = document.getElementById("sync-pending-badge");
        if (badge) {
          badge.classList.remove("hidden");
          badge.classList.add("flex");
        }
      } else {
        await refreshActiveWorkspace();
        showToast("Synced external disk changes", "info");
      }
    });
  }

  async function flushDeferredReload() {
    deferredReload = false;
    const badge = document.getElementById("sync-pending-badge");
    if (badge) {
      badge.classList.add("hidden");
      badge.classList.remove("flex");
    }
    await refreshActiveWorkspace();
  }

  function checkFlushDeferredReload() {
    if (deferredReload && !isAnyModalOpen()) {
      flushDeferredReload();
    }
  }

  // --- Global Keyboard & Click Listeners ---
  document.addEventListener("keydown", (event) => {
    const tag = (event.target.tagName || "").toLowerCase();
    const isInput = tag === "input" || tag === "textarea" || tag === "select" || event.target.isContentEditable;

    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      openSearchModal();
      return;
    }
    if (!isInput && event.key === "/" && !isAnyModalOpen()) {
      event.preventDefault();
      openSearchModal();
      return;
    }
    if (event.key === "Escape") {
      hideContextMenu();
      if (!document.getElementById("search-modal").classList.contains("hidden")) closeSearchModal();
      if (!document.getElementById("tile-modal").classList.contains("hidden")) closeTileModal();
      if (!document.getElementById("mix-modal").classList.contains("hidden")) closeMixModal();
    }
  });

  document.addEventListener("click", (event) => {
    const menu = document.getElementById("tile-context-menu");
    if (menu && !menu.classList.contains("hidden") && !menu.contains(event.target)) {
      hideContextMenu();
    }
  });

  document.body.addEventListener("htmx:afterSwap", () => {
    refreshIcons();
  });

  document.addEventListener("DOMContentLoaded", () => {
    refreshIcons();
    initSSE();
  });

  return {
    onTileDragStart,
    onSlotDragOver,
    onSlotDragLeave,
    onSlotDrop,
    onTileDragEnd,
    onTileClick,
    onTabDragStart,
    onTabDragOver,
    onTabDrop,
    onTabDragEnd,
    onTileContextMenu,
    onTileMenuButton,
    ctxEditTile,
    ctxDuplicateTile,
    ctxTransferTile,
    ctxDeleteTile,
    openCreateTileModal,
    openEditTileModal,
    closeTileModal,
    setTileBgColor,
    setTileTextColor,
    setIconMode,
    selectLucideIcon,
    filterLucideIcons,
    onTileUrlInput,
    fetchSiteMetadata,
    uploadCustomIcon,
    updateTilePreview,
    submitTileForm,
    openCreateMixModal,
    openEditMixModal,
    closeMixModal,
    checkMixBoundsWarning,
    submitMixForm,
    confirmDeleteActiveMix,
    openSearchModal,
    closeSearchModal,
    onSearchInput,
    onSearchKeyDown,
    setSearchIndex,
    activateSearchResult,
    flushDeferredReload,
  };
})();
