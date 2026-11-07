/* EffectiveTube front-end: progressive enhancement over the JSON API. */
(() => {
  "use strict";

  const body = document.body;
  const API = "/api/v1";

  // ------------------------------------------------------------------ utils
  function toast(message, kind = "info", timeout = 3500) {
    const stack = document.getElementById("toasts");
    if (!stack) return;
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = message;
    stack.appendChild(el);
    setTimeout(() => el.remove(), timeout);
  }

  function csrf() {
    // The refresh endpoint rotates the CSRF cookie together with the session.
    // Do not keep using the token rendered into the page before that rotation.
    const cookie = document.cookie
      .split(";")
      .map((part) => part.trim())
      .find((part) => part.startsWith("et_csrf="));
    return cookie ? decodeURIComponent(cookie.slice("et_csrf=".length)) : (body.dataset.csrf || "");
  }

  async function refreshSession() {
    const res = await fetch(`${API}/auth/refresh`, {
      method: "POST",
      credentials: "same-origin",
    });
    return res.ok;
  }

  async function api(path, options = {}, retried = false) {
    const method = (options.method || "GET").toUpperCase();
    const headers = new Headers(options.headers || {});
    let payload = options.body;
    if (payload && !(payload instanceof FormData)) {
      headers.set("Content-Type", "application/json");
      payload = JSON.stringify(payload);
    }
    if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
      headers.set("X-CSRF-Token", csrf());
    }
    const res = await fetch(`${API}${path}`, {
      method,
      headers,
      body: payload,
      credentials: "same-origin",
    });
    if (res.status === 401 && !retried && !path.startsWith("/auth/")) {
      if (await refreshSession()) return api(path, options, true);
      window.location.href = "/login";
      throw new Error("Требуется вход");
    }
    if (!res.ok) {
      let detail = `Ошибка ${res.status}`;
      try {
        const data = await res.json();
        if (data.detail) detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      } catch (_) { /* ignore */ }
      const error = new Error(detail);
      error.status = res.status;
      throw error;
    }
    if (res.status === 204) return null;
    return res.json();
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function initials(name) {
    return (name || "?").trim().slice(0, 1).toUpperCase();
  }

  function formatCount(n) {
    return new Intl.NumberFormat("ru-RU").format(n || 0);
  }

  // ------------------------------------------------------------------ theme
  const themeToggle = document.getElementById("theme-toggle");
  const storedTheme = localStorage.getItem("et-theme");
  if (storedTheme) document.documentElement.dataset.theme = storedTheme;
  themeToggle?.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("et-theme", next);
  });

  // ---------------------------------------------------------------- sidebar
  const sidebarToggle = document.getElementById("sidebar-toggle");
  const sidebarScrim = document.getElementById("sidebar-scrim");
  if (window.innerWidth > 1100) {
    if (localStorage.getItem("et-sidebar") === "collapsed") body.classList.add("sidebar-collapsed");
  }
  sidebarToggle?.addEventListener("click", () => {
    if (window.innerWidth <= 1100) {
      body.classList.toggle("sidebar-open");
      if (sidebarScrim) sidebarScrim.hidden = !body.classList.contains("sidebar-open");
    } else {
      body.classList.toggle("sidebar-collapsed");
      localStorage.setItem(
        "et-sidebar",
        body.classList.contains("sidebar-collapsed") ? "collapsed" : "open"
      );
    }
  });
  sidebarScrim?.addEventListener("click", () => {
    body.classList.remove("sidebar-open");
    sidebarScrim.hidden = true;
  });

  // --------------------------------------------------------------- dropdown
  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-dropdown-toggle]");
    if (toggle) {
      const wrap = toggle.closest("[data-dropdown]");
      const menu = wrap?.querySelector("[data-dropdown-menu]");
      if (menu) {
        event.preventDefault();
        const willShow = menu.hidden;
        document.querySelectorAll("[data-dropdown-menu]").forEach((m) => (m.hidden = true));
        menu.hidden = !willShow;
      }
      return;
    }
    if (!event.target.closest("[data-dropdown-menu]")) {
      document.querySelectorAll("[data-dropdown-menu]").forEach((m) => (m.hidden = true));
    }
  });

  // ------------------------------------------------------------------ modal
  function openModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.hidden = false;
  }
  function closeModals() {
    document.querySelectorAll(".modal").forEach((m) => (m.hidden = true));
  }
  document.querySelectorAll(".modal").forEach((modal) => {
    modal.addEventListener("click", (event) => {
      if (event.target === modal) modal.hidden = true;
    });
  });

  // ----------------------------------------------------------------- logout
  document.addEventListener("click", async (event) => {
    const btn = event.target.closest('[data-action="logout"]');
    if (!btn) return;
    try {
      await api("/auth/logout", { method: "POST" });
      window.location.href = "/";
    } catch (error) {
      toast(error.message, "error");
    }
  });

  // ------------------------------------------------------------------- auth
  document.querySelectorAll('[data-form="login"], [data-form="register"]').forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const errorBox = form.querySelector("[data-form-error]");
      const button = form.querySelector('button[type="submit"]');
      if (errorBox) errorBox.hidden = true;
      button.disabled = true;
      const data = Object.fromEntries(new FormData(form).entries());
      try {
        if (form.dataset.form === "login") {
          await api("/auth/login", {
            method: "POST",
            body: { login: data.login, password: data.password },
          });
        } else {
          await api("/auth/register", {
            method: "POST",
            body: {
              display_name: data.display_name,
              username: data.username,
              email: data.email,
              password: data.password,
            },
          });
        }
        window.location.href = form.dataset.next || "/";
      } catch (error) {
        if (errorBox) {
          errorBox.textContent = error.message;
          errorBox.hidden = false;
        } else {
          toast(error.message, "error");
        }
      } finally {
        button.disabled = false;
      }
    });
  });

  // ------------------------------------------------------------- like buttons
  document.addEventListener("click", async (event) => {
    const btn = event.target.closest('[data-action="like"]');
    if (!btn) return;
    if (body.dataset.auth !== "1") {
      window.location.href = "/login";
      return;
    }
    const videoId = btn.dataset.video;
    const value = Number(btn.dataset.value);
    const group = btn.closest(".like-group");
    const isActive = btn.classList.contains("active");
    const nextValue = isActive ? 0 : value;
    try {
      const state = await api(`/videos/${videoId}/like`, { method: "PUT", body: { value: nextValue } });
      group.querySelectorAll("[data-action='like']").forEach((b) => b.classList.remove("active"));
      if (state.my_value === 1) group.querySelector('[data-value="1"]').classList.add("active");
      if (state.my_value === -1) group.querySelector('[data-value="-1"]').classList.add("active");
      const likeCounter = group.querySelector("[data-like-count]");
      const dislikeCounter = group.querySelector("[data-dislike-count]");
      if (likeCounter) likeCounter.textContent = formatCount(state.likes);
      if (dislikeCounter) dislikeCounter.textContent = formatCount(state.dislikes);
    } catch (error) {
      toast(error.message, "error");
    }
  });

  // -------------------------------------------------------------- subscribe
  document.addEventListener("click", async (event) => {
    const btn = event.target.closest('[data-action="subscribe"]');
    if (!btn) return;
    if (body.dataset.auth !== "1") {
      window.location.href = "/login";
      return;
    }
    const channel = btn.dataset.channel;
    const subscribed = btn.classList.contains("subscribed");
    try {
      await api(`/channels/${encodeURIComponent(channel)}/subscribe`, {
        method: subscribed ? "DELETE" : "POST",
      });
      btn.classList.toggle("subscribed", !subscribed);
      btn.textContent = subscribed ? "Подписаться" : "Вы подписаны";
      toast(subscribed ? "Вы отписались" : "Вы подписались", "success");
    } catch (error) {
      toast(error.message, "error");
    }
  });

  // -------------------------------------------------------------- comments
  function buildComment(comment, { isReply = false } = {}) {
    const wrap = el("div", "comment");
    wrap.dataset.commentId = comment.id;
    const link = el("a");
    link.href = comment.author ? `/@${comment.author.username}` : "#";
    const img = el("img", "avatar sm");
    img.src = comment.author?.avatar_url || "";
    img.alt = "";
    link.appendChild(img);
    wrap.appendChild(link);

    const bodyEl = el("div", "comment-body");
    const head = el("div", "comment-head");
    const author = el("a", "comment-author", comment.author ? `@${comment.author.username}` : "Пользователь");
    author.href = comment.author ? `/@${comment.author.username}` : "#";
    head.appendChild(author);
    head.appendChild(el("span", "comment-age", "только что"));
    bodyEl.appendChild(head);
    bodyEl.appendChild(el("div", "comment-text", comment.body));

    const actions = el("div", "comment-actions");
    if (!isReply && body.dataset.auth === "1") {
      const replyBtn = el("button", "", "Ответить");
      replyBtn.type = "button";
      replyBtn.dataset.action = "reply";
      replyBtn.dataset.comment = comment.id;
      replyBtn.dataset.author = comment.author?.username || "";
      actions.appendChild(replyBtn);
    }
    const deleteBtn = el("button", "", "Удалить");
    deleteBtn.type = "button";
    deleteBtn.dataset.action = "comment-delete";
    deleteBtn.dataset.comment = comment.id;
    actions.appendChild(deleteBtn);
    bodyEl.appendChild(actions);

    const repliesEl = el("div", "replies");
    bodyEl.appendChild(repliesEl);
    wrap.appendChild(bodyEl);
    return wrap;
  }

  function findComment(id) {
    return document.querySelector(`[data-comment-id="${id}"]`);
  }

  document.addEventListener("click", (event) => {
    const replyBtn = event.target.closest('[data-action="reply"]');
    if (replyBtn) {
      const comment = findComment(replyBtn.dataset.comment);
      const form = comment?.querySelector('[data-form="reply"]');
      if (form) {
        form.hidden = !form.hidden;
        if (!form.hidden) form.querySelector("textarea")?.focus();
      }
      return;
    }
    const cancel = event.target.closest('[data-action="reply-cancel"]');
    if (cancel) {
      const form = cancel.closest("form");
      if (form) form.hidden = true;
      return;
    }
    const cancelComment = event.target.closest('[data-action="comment-cancel"]');
    if (cancelComment) {
      const form = cancelComment.closest("form");
      form.reset();
      form.querySelector("[data-comment-submit]").disabled = true;
      return;
    }
    const remove = event.target.closest('[data-action="comment-delete"]');
    if (remove) {
      const id = remove.dataset.comment;
      if (!window.confirm("Удалить комментарий?")) return;
      api(`/videos/comments/${id}`, { method: "DELETE" })
        .then(() => {
          const node = findComment(id);
          if (node) {
            node.classList.add("deleted");
            node.querySelectorAll(".comment-body").forEach((b) => {
              if (!b.closest(".comment").querySelector(".replies")) return;
            });
            const text = node.querySelector(".comment-text");
            if (text) text.textContent = "Комментарий удалён";
            const actions = node.querySelector(".comment-actions");
            if (actions) actions.innerHTML = "";
          }
          toast("Комментарий удалён", "success");
        })
        .catch((e) => toast(e.message, "error"));
    }
  });

  // enable comment submit buttons when text is present
  document.addEventListener("input", (event) => {
    if (!event.target.matches("textarea")) return;
    const form = event.target.closest("form");
    const submit = form?.querySelector("[data-comment-submit]");
    if (submit) submit.disabled = event.target.value.trim().length === 0;
  });

  document.querySelectorAll('[data-form="comment"]').forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const textarea = form.querySelector("textarea");
      const value = textarea.value.trim();
      if (!value) return;
      const submit = form.querySelector("[data-comment-submit]");
      if (submit) submit.disabled = true;
      try {
        const comment = await api(`/videos/${form.dataset.video}/comments`, {
          method: "POST",
          body: { body: value },
        });
        const list = document.querySelector("[data-comment-list]");
        if (list) list.prepend(buildComment(comment));
        textarea.value = "";
        toast("Комментарий добавлен", "success");
      } catch (error) {
        toast(error.message, "error");
      } finally {
        if (submit) submit.disabled = true;
      }
    });
  });

  document.querySelectorAll('[data-form="reply"]').forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const textarea = form.querySelector("textarea");
      const value = textarea.value.trim();
      if (!value) return;
      try {
        const comment = await api(`/videos/${form.dataset.video}/comments`, {
          method: "POST",
          body: { body: value, parent_id: form.dataset.comment },
        });
        const parent = findComment(form.dataset.comment);
        let replies = parent?.querySelector(".replies");
        if (parent && !replies) {
          replies = el("div", "replies");
          parent.querySelector(".comment-body").appendChild(replies);
        }
        if (replies) replies.appendChild(buildComment(comment, { isReply: true }));
        textarea.value = "";
        form.hidden = true;
        toast("Ответ добавлен", "success");
      } catch (error) {
        toast(error.message, "error");
      }
    });
  });

  // load more comments
  document.addEventListener("click", async (event) => {
    const btn = event.target.closest('[data-action="comments-more"]');
    if (!btn) return;
    const videoId = btn.dataset.video;
    const list = document.querySelector("[data-comment-list]");
    const current = list ? list.querySelectorAll(":scope > .comment").length : 0;
    const page = Math.floor(current / 20) + 1;
    btn.disabled = true;
    try {
      const data = await api(`/videos/${videoId}/comments?page=${page}&page_size=20`);
      if (!data.items.length) {
        btn.remove();
        return;
      }
      data.items.forEach((comment) => list.appendChild(buildComment(comment)));
      if (!data.has_more) btn.remove();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      btn.disabled = false;
    }
  });

  // ---------------------------------------------------------------- watch page
  const watchRoot = document.querySelector("[data-watch]");
  if (watchRoot) {
    const videoId = watchRoot.dataset.videoId;
    const player = document.getElementById("player");
    if (player) {
      let counted = false;
      player.addEventListener("play", async () => {
        if (counted) return;
        counted = true;
        try {
          const result = await api(`/videos/${videoId}/view`, { method: "POST" });
          if (result.counted) {
            const stats = document.querySelector(".description-stats");
            if (stats) stats.textContent = stats.textContent.replace(/^[^·]+/, `${formatCount(result.views)} просмотров `);
          }
        } catch (_) { /* views are best-effort */ }
      }, { once: true });
    }
  }

  document.addEventListener("click", async (event) => {
    const share = event.target.closest('[data-action="share"]');
    if (share) {
      const url = `${window.location.origin}/watch/${share.dataset.video}`;
      try {
        if (navigator.share) await navigator.share({ url });
        else {
          await navigator.clipboard.writeText(url);
          toast("Ссылка скопирована", "success");
        }
      } catch (_) { /* user cancelled */ }
      return;
    }

    const grant = event.target.closest('[data-action="access-revoke"]');
    if (grant) {
      try {
        await api(`/videos/${grant.dataset.video}/access/${encodeURIComponent(grant.dataset.user)}`, {
          method: "DELETE",
        });
        grant.closest(".acl-chip")?.remove();
        toast("Доступ отозван", "success");
      } catch (error) {
        toast(error.message, "error");
      }
      return;
    }

    const report = event.target.closest('[data-action="report"]');
    if (report) {
      if (body.dataset.auth !== "1") {
        window.location.href = "/login";
        return;
      }
      const form = document.querySelector('[data-form="report"]');
      if (form) form.dataset.video = report.dataset.video;
      openModal("report-modal");
      return;
    }

    const addToPlaylist = event.target.closest('[data-action="playlist-add"]');
    if (addToPlaylist) {
      try {
        await api(`/playlists/${addToPlaylist.dataset.playlist}/items`, {
          method: "POST",
          body: { video_id: addToPlaylist.dataset.video },
        });
        toast("Добавлено в плейлист", "success");
      } catch (error) {
        toast(error.message, "error");
      }
      return;
    }

    const createPlaylist = event.target.closest('[data-action="playlist-create"]');
    if (createPlaylist) {
      const title = window.prompt("Название плейлиста");
      if (!title) return;
      try {
        const playlist = await api("/playlists", {
          method: "POST",
          body: { title, visibility: "private" },
        });
        await api(`/playlists/${playlist.id}/items`, {
          method: "POST",
          body: { video_id: createPlaylist.dataset.video },
        });
        toast("Плейлист создан", "success");
      } catch (error) {
        toast(error.message, "error");
      }
      return;
    }

    if (event.target.closest('[data-action="modal-close"]')) {
      closeModals();
    }
  });

  const accessForm = document.querySelector('[data-form="access-grant"]');
  accessForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const username = accessForm.querySelector("input").value.trim();
    if (!username) return;
    try {
      await api(`/videos/${accessForm.dataset.video}/access`, {
        method: "POST",
        body: { username },
      });
      window.location.reload();
    } catch (error) {
      toast(error.message, "error");
    }
  });

  const reportForm = document.querySelector('[data-form="report"]');
  reportForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(reportForm).entries());
    try {
      await api(`/videos/${reportForm.dataset.video}/report`, {
        method: "POST",
        body: { reason: data.reason, details: data.details || "" },
      });
      closeModals();
      toast("Жалоба отправлена модераторам", "success");
    } catch (error) {
      toast(error.message, "error");
    }
  });

  // ------------------------------------------------------------------ upload
  const uploadRoot = document.querySelector("[data-upload]");
  if (uploadRoot) {
    const form = uploadRoot.querySelector('[data-form="upload"]');
    const fileInput = document.getElementById("file-input");
    const dropzone = document.getElementById("dropzone");
    const emptyState = dropzone?.querySelector("[data-dropzone-empty]");
    const fileState = dropzone?.querySelector("[data-dropzone-file]");
    const submitBtn = form?.querySelector("[data-upload-submit]");
    const statusBox = form?.querySelector("[data-upload-status]");
    const maxMb = Number(uploadRoot.dataset.maxMb || 2048);
    let selectedFile = null;
    let uploading = false;

    function setFile(file) {
      if (!file) return;
      if (!file.type.startsWith("video/") && !/\.(mp4|mov|webm|mkv|avi|m4v)$/i.test(file.name)) {
        toast("Выберите видеофайл", "error");
        return;
      }
      if (file.size > maxMb * 1024 * 1024) {
        toast(`Файл больше ${maxMb} МБ`, "error");
        return;
      }
      selectedFile = file;
      if (emptyState) emptyState.hidden = true;
      if (fileState) fileState.hidden = false;
      dropzone.querySelector("[data-file-name]").textContent = file.name;
      dropzone.querySelector("[data-file-size]").textContent = `${(file.size / 1024 / 1024).toFixed(1)} МБ`;
      submitBtn.disabled = false;
      const titleInput = form.querySelector('[name="title"]');
      if (titleInput && !titleInput.value) {
        titleInput.value = file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").slice(0, 200);
      }
    }

    dropzone?.addEventListener("click", (event) => {
      if (!event.target.closest('[data-action="file-clear"]')) fileInput.click();
    });
    dropzone?.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") fileInput.click();
    });
    fileInput?.addEventListener("change", () => setFile(fileInput.files[0]));
    ["dragenter", "dragover"].forEach((name) =>
      dropzone?.addEventListener(name, (event) => {
        event.preventDefault();
        dropzone.classList.add("dragover");
      })
    );
    ["dragleave", "drop"].forEach((name) =>
      dropzone?.addEventListener(name, (event) => {
        event.preventDefault();
        dropzone.classList.remove("dragover");
      })
    );
    dropzone?.addEventListener("drop", (event) => setFile(event.dataTransfer.files[0]));

    document.addEventListener("click", (event) => {
      if (!event.target.closest('[data-action="file-clear"]')) return;
      event.stopPropagation();
      selectedFile = null;
      fileInput.value = "";
      if (emptyState) emptyState.hidden = false;
      if (fileState) fileState.hidden = true;
      submitBtn.disabled = true;
      const progressWrap = dropzone.querySelector("[data-progress-wrap]");
      if (progressWrap) progressWrap.hidden = true;
    });

    form?.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (uploading) return;
      if (!selectedFile) {
        toast("Сначала выберите файл", "error");
        return;
      }
      const data = Object.fromEntries(new FormData(form).entries());
      if (!String(data.title || "").trim()) {
        toast("Добавьте название", "error");
        return;
      }
      uploading = true;
      submitBtn.disabled = true;
      const progressWrap = dropzone.querySelector("[data-progress-wrap]");
      const progressBar = dropzone.querySelector("[data-progress-bar]");
      const progressText = dropzone.querySelector("[data-progress-text]");
      const progressStatus = dropzone.querySelector("[data-progress-status]");
      if (progressWrap) progressWrap.hidden = false;
      if (statusBox) statusBox.hidden = false;
      const setStatus = (text) => {
        if (progressStatus) progressStatus.textContent = text;
        if (statusBox) statusBox.textContent = text;
      };

      try {
        setStatus("Создаём запись видео…");
        const video = await api("/videos", {
          method: "POST",
          body: {
            title: String(data.title).trim(),
            description: String(data.description || ""),
            visibility: data.visibility || "public",
          },
        });

        setStatus("Загружаем файл…");
        await new Promise((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open("POST", `${API}/videos/${video.id}/file`);
          xhr.setRequestHeader("X-CSRF-Token", csrf());
          xhr.upload.addEventListener("progress", (e) => {
            if (!e.lengthComputable) return;
            const percent = Math.round((e.loaded / e.total) * 100);
            if (progressBar) progressBar.style.width = `${percent}%`;
            if (progressText) progressText.textContent = `${percent}%`;
          });
          xhr.addEventListener("load", () => {
            if (xhr.status >= 200 && xhr.status < 300) resolve();
            else {
              let detail = `Ошибка загрузки (${xhr.status})`;
              try { detail = JSON.parse(xhr.responseText).detail || detail; } catch (_) { /* ignore */ }
              reject(new Error(detail));
            }
          });
          xhr.addEventListener("error", () => reject(new Error("Сетевая ошибка при загрузке")));
          const payload = new FormData();
          payload.append("file", selectedFile, selectedFile.name);
          xhr.send(payload);
        });

        if (data.playlist_id) {
          try {
            await api(`/playlists/${data.playlist_id}/items`, {
              method: "POST",
              body: { video_id: video.id },
            });
          } catch (_) { /* playlist is optional */ }
        }

        setStatus("Обрабатываем видео: транскодирование и превью…");
        let attempts = 0;
        while (attempts < 200) {
          attempts += 1;
          await new Promise((r) => setTimeout(r, 3000));
          const current = await api(`/videos/${video.id}`);
          if (current.status === "ready") {
            if (progressBar) progressBar.style.width = "100%";
            setStatus("Готово! Открываем видео…");
            window.location.href = `/watch/${video.id}`;
            return;
          }
          if (current.status === "failed") {
            throw new Error("Не удалось обработать видео. Попробуйте другой файл.");
          }
        }
        toast("Видео всё ещё обрабатывается — оно появится в студии", "info");
        window.location.href = "/studio";
      } catch (error) {
        toast(error.message, "error");
        setStatus(error.message);
        uploading = false;
        submitBtn.disabled = false;
      }
    });
  }

  // ------------------------------------------------------------------ studio
  document.querySelectorAll("[data-studio-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll("[data-studio-tab]").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      document.querySelectorAll("[data-studio-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.studioPanel !== tab.dataset.studioTab;
      });
    });
  });

  document.addEventListener("click", async (event) => {
    const edit = event.target.closest('[data-action="video-edit"]');
    if (edit) {
      const form = document.querySelector('[data-form="video-edit"]');
      form.querySelector('[name="video_id"]').value = edit.dataset.video;
      form.querySelector('[name="title"]').value = edit.dataset.title;
      form.querySelector('[name="description"]').value = edit.dataset.description || "";
      form.querySelector('[name="visibility"]').value = edit.dataset.visibility;
      openModal("edit-modal");
      return;
    }

    const del = event.target.closest('[data-action="video-delete"]');
    if (del) {
      if (!window.confirm("Удалить видео безвозвратно?")) return;
      try {
        await api(`/videos/${del.dataset.video}`, { method: "DELETE" });
        del.closest("[data-video-row]")?.remove();
        toast("Видео удалено", "success");
      } catch (error) {
        toast(error.message, "error");
      }
      return;
    }

    const playlistDelete = event.target.closest('[data-action="playlist-delete"]');
    if (playlistDelete) {
      if (!window.confirm("Удалить плейлист?")) return;
      try {
        await api(`/playlists/${playlistDelete.dataset.playlist}`, { method: "DELETE" });
        window.location.href = "/studio";
      } catch (error) {
        toast(error.message, "error");
      }
      return;
    }

    const playlistRemove = event.target.closest('[data-action="playlist-remove"]');
    if (playlistRemove) {
      try {
        await api(`/playlists/${playlistRemove.dataset.playlist}/items/${playlistRemove.dataset.video}`, {
          method: "DELETE",
        });
        playlistRemove.closest("[data-playlist-video]")?.remove();
        toast("Видео убрано из плейлиста", "success");
      } catch (error) {
        toast(error.message, "error");
      }
    }
  });

  const editForm = document.querySelector('[data-form="video-edit"]');
  editForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(editForm).entries());
    try {
      await api(`/videos/${data.video_id}`, {
        method: "PATCH",
        body: {
          title: data.title,
          description: data.description,
          visibility: data.visibility,
        },
      });
      window.location.reload();
    } catch (error) {
      toast(error.message, "error");
    }
  });

  const playlistForm = document.querySelector('[data-form="playlist-create"]');
  playlistForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(playlistForm).entries());
    try {
      await api("/playlists", { method: "POST", body: data });
      window.location.reload();
    } catch (error) {
      toast(error.message, "error");
    }
  });

  // -------------------------------------------------------------- moderation
  document.querySelectorAll('[data-action="report-resolve"]').forEach((button) => {
    button.addEventListener("click", async () => {
      const { report, resolution } = button.dataset;
      const labels = { dismiss: "Отклонить жалобу?", hide: "Скрыть видео?", remove: "Удалить видео модерацией?" };
      if (!window.confirm(labels[resolution] || "Подтвердить действие?")) return;
      try {
        await api(`/moderation/reports/${report}/resolve`, {
          method: "POST",
          body: { action: resolution, note: "" },
        });
        button.closest("[data-report-id]")?.remove();
        toast("Решение применено", "success");
      } catch (error) {
        toast(error.message, "error");
      }
    });
  });

  // ------------------------------------------------------------------- admin
  document.querySelectorAll('[data-action="role-change"]').forEach((select) => {
    select.addEventListener("change", async () => {
      try {
        await api(`/admin/users/${select.dataset.user}/role`, {
          method: "PATCH",
          body: { role: select.value },
        });
        toast("Роль обновлена", "success");
      } catch (error) {
        toast(error.message, "error");
        window.location.reload();
      }
    });
  });

  document.querySelectorAll('[data-action="active-toggle"]').forEach((button) => {
    button.addEventListener("click", async () => {
      const nextActive = button.dataset.active !== "1";
      try {
        await api(`/admin/users/${button.dataset.user}/active`, {
          method: "PATCH",
          body: { is_active: nextActive },
        });
        button.dataset.active = nextActive ? "1" : "0";
        button.textContent = nextActive ? "Активен" : "Отключён";
        button.classList.toggle("ok-text", nextActive);
        button.classList.toggle("danger-text", !nextActive);
        toast("Статус обновлён", "success");
      } catch (error) {
        toast(error.message, "error");
      }
    });
  });
})();
