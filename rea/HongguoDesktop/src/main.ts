import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import "./style.css";

type Mode = "rank" | "category" | "latest" | "search";
type Card = {
  series_id: string;
  title: string;
  cover: string;
  episode_cnt: number;
  score: string;
  intro?: string;
};
type Page = {
  items: Card[];
  has_more: boolean;
  next_cursor: unknown;
  warnings?: string[];
};
type Filter = {
  type: string;
  row_name: string;
  selection_type: number;
  items: { selector_item_id: string; show_name: string }[];
};
type Episode = { index: number; vid: string; title: string };
type Detail = {
  series_id: string;
  meta: Card & { intro: string; status: string; play_cnt: string };
  episodes: Episode[];
  complete: boolean;
  issues: string[];
};
type Playback = {
  id: string;
  request_id: string;
  status: "preparing" | "ready" | "failed";
  phase: string;
  revision: number;
  url?: string;
  error?: string;
  model_api?: string;
  model_api_state?: string;
  model_fallback?: boolean;
  model_fallback_reason?: string;
};
type Job = {
  id: string;
  series_id: string;
  title: string;
  vid: string;
  index: number;
  quality: string;
  status: string;
  progress: number;
  file: string;
  error: string;
  received?: number;
  total?: number;
  revision?: number;
  model_api?: string;
  model_api_state?: string;
  model_fallback?: boolean;
  model_fallback_reason?: string;
};
type List = {
  mode: Mode;
  items: Card[];
  cursor: unknown;
  more: boolean;
  loading: boolean;
  loaded: boolean;
  error: string;
  warnings: string[];
  scroll: number;
  params: Record<string, unknown>;
};
const active = new Set([
  "queued",
  "preparing",
  "downloading",
  "decrypting",
  "verifying",
  "cancelling",
]);
const labels: Record<string, string> = {
  queued: "等待下载",
  preparing: "获取视频",
  downloading: "下载中",
  decrypting: "解密中",
  verifying: "校验音视频",
  completed: "已完成",
  failed: "下载失败",
  cancelled: "已取消",
  interrupted: "等待重试",
  cancelling: "正在取消",
};
const icons: Record<string, string> = {
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
  download: '<path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4"/>',
  play: '<path d="m9 5 11 7-11 7z"/>',
  arrow: '<path d="m14 6-6 6 6 6M8 12h13"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  folder: '<path d="M3 7h7l2 2h9v11H3zM3 7V4h7l2 3h8v2"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2 6M20 4v7h-7"/>',
  rank: '<path d="M5 20V10h5v10m0 0V4h5v16m0 0v-7h5v7"/>',
  filter:
    '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="2"/><circle cx="15" cy="17" r="2"/>',
  new: '<path d="m12 2 2.6 7.4L22 12l-7.4 2.6L12 22l-2.6-7.4L2 12l7.4-2.6z"/>',
};
const icon = (name: string) =>
  `<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.download}</svg>`;
const esc = (value: unknown) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ]!,
  );
let pendingDownloads = 0;
const call = async <T>(method: string, params: unknown = {}): Promise<T> => {
  const mutation = method === "enqueue" || method === "retry";
  if (mutation) pendingDownloads++;
  try {
    return await invoke<T>("backend_call", { method, params });
  } finally {
    if (mutation) pendingDownloads--;
  }
};
const blank = (mode: Mode, params: Record<string, unknown>): List => ({
  mode,
  params,
  items: [],
  cursor: null,
  more: false,
  loading: false,
  loaded: false,
  error: "",
  warnings: [],
  scroll: 0,
});
const lists: Record<Mode, List> = {
  rank: blank("rank", { category: "all", board: "hot" }),
  category: blank("category", { genre: "short_play", selections: {} }),
  latest: blank("latest", { genre: "short_play" }),
  search: blank("search", { query: "" }),
};
let mode: Mode = "rank";
let detail: Detail | null = null,
  detailId = "",
  detailLoading = false,
  detailError = "",
  detailGeneration = 0;
let quality = "1080p",
  episodeRange = 0,
  jobs: Job[] = [],
  directory = "",
  drawer = false;
let filters: Filter[] = [],
  filtersGenre = "",
  filtersError = "",
  filtersLoading = false,
  filterGeneration = 0;
let expandedFilters = false;
let toastTimer: ReturnType<typeof setTimeout>;
let quitting = false;
let player: {
  requestId: string;
  detail: Detail;
  index: number;
  quality: string;
  state?: Playback;
  mediaError?: string;
  cancelBuffering?: () => void;
} | null = null;
let playerFocus: HTMLElement | null = null;
const app = document.querySelector<HTMLDivElement>("#app")!;
app.innerHTML = `
  <div class="titlebar" data-tauri-drag-region><span data-tauri-drag-region>HONGGUO DESKTOP</span></div>
  <header class="header">
    <button class="brand" id="home" aria-label="返回榜单首页"><span class="brand-mark"><i></i></span><span>红果<span class="brand-sub">好故事，随时收藏</span></span></button>
    <form id="search-form" class="searchbox">${icon("search")}<input id="query" type="search" placeholder="搜索剧名，发现下一部好剧" autocomplete="off" maxlength="100" aria-label="搜索剧名"><kbd>↵</kbd></form>
    <button id="tasks" class="task-toggle">${icon("download")}<span>下载任务</span><span id="task-count" class="count">0</span></button>
  </header>
  <nav class="nav" aria-label="找剧方式"><div id="nav-tabs"></div><span class="nav-note"><i></i> 好故事，每天发现</span></nav>
  <main id="workspace" tabindex="-1"></main>
  <footer class="footer"><span>HONGGUO<span class="footer-dot">·</span> 让好故事留在身边</span><button id="save-location" title="更改下载位置">${icon("folder")}<span id="location-label">下载位置</span></button></footer>
  <div id="drawer-root"></div><div id="player-root"></div><div id="modal-root"></div><div id="toast" role="status" aria-live="polite"></div>`;
const workspace = document.querySelector<HTMLElement>("#workspace")!;

function toast(message: string) {
  const el = document.querySelector<HTMLElement>("#toast")!;
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 4200);
}
function renderNav() {
  document.querySelector("#nav-tabs")!.innerHTML = (
    ["rank", "category", "latest"] as Mode[]
  )
    .map(
      (m) =>
        `<button data-mode="${m}" class="nav-tab ${mode === m && !detailId ? "selected" : ""}">${icon({ rank: "rank", category: "filter", latest: "new", search: "search" }[m])}${{ rank: "排行榜", category: "分类探索", latest: "最新上架", search: "" }[m]}</button>`,
    )
    .join("");
}
function chip(group: string, value: string, label: string, selected: boolean) {
  return `<button class="chip ${selected ? "selected" : ""}" data-group="${esc(group)}" data-value="${esc(value)}" aria-pressed="${selected}">${esc(label)}</button>`;
}
function filtersHTML(list: List) {
  if (mode === "rank")
    return `<div class="filters rank-filters"><div class="chips">${[
      ["all", "全部"],
      ["human", "真人剧"],
      ["comic", "漫剧"],
      ["ai", "AI剧"],
    ]
      .map(([id, label]) =>
        chip("category", id, label, list.params.category === id),
      )
      .join("")}</div><div class="segmented">${[
      ["recommend", "推荐榜"],
      ["hot", "热播榜"],
      ["new", "新剧榜"],
    ]
      .map(([id, label]) => chip("board", id, label, list.params.board === id))
      .join("")}</div></div>`;
  if (mode === "search") return "";
  const genres = [
    ["short_play", "真人剧"],
    ["comic_series", "漫剧"],
    ["ai_series", "AI剧"],
  ];
  const genreBar = `<div class="filter-line"><span class="filter-label">体裁</span><div class="chips">${genres.map(([id, label]) => chip("genre", id, label, list.params.genre === id)).join("")}</div></div>`;
  if (mode === "latest") return `<div class="filters">${genreBar}</div>`;
  if (filtersLoading)
    return `<div class="filters">${genreBar}<div class="muted filter-loading">正在加载分类选项…</div></div>`;
  const selections = list.params.selections as Record<string, string[]>;
  const rows = filters.filter(
    (r) =>
      r.type !== "genre" &&
      (expandedFilters ||
        ["category_dim_theme", "category_dim_role"].includes(r.type)),
  );
  const summary = filters
    .filter(
      (r) =>
        !["genre", "sort", "category_dim_theme", "category_dim_role"].includes(
          r.type,
        ),
    )
    .flatMap((r) =>
      r.items
        .filter((i) => selections[r.type]?.includes(i.selector_item_id))
        .map((i) => i.show_name),
    )
    .join(" · ");
  return `<div class="filters category-filters">${genreBar}${
    filtersError
      ? `<div class="inline-error">${esc(filtersError)} <button data-action="filter-retry">重试</button></div>`
      : rows
          .map(
            (row) =>
              `<div class="filter-line"><span class="filter-label">${esc(row.row_name.replace(/^全部/, ""))}</span><div class="chips">${row.type !== "sort" ? chip(row.type, "", "全部", !selections[row.type]?.length) : ""}${row.items
                .filter(
                  (item, i) =>
                    expandedFilters ||
                    i < 8 ||
                    selections[row.type]?.includes(item.selector_item_id),
                )
                .map((item) =>
                  chip(
                    row.type,
                    item.selector_item_id,
                    item.show_name,
                    (
                      selections[row.type] ||
                      (row.type === "sort" ? ["online_time"] : [])
                    ).includes(item.selector_item_id),
                  ),
                )
                .join("")}</div></div>`,
          )
          .join("")
  }<div class="filter-expand"><span>${expandedFilters ? "筛选来自平台，每种体裁的选项会有所不同" : esc(summary || "还有更多主题、设定、背景与排序方式")}</span><button data-action="expand-filters">${expandedFilters ? "收起筛选 ↑" : "展开全部筛选 ↓"}</button></div></div>`;
}
function poster(card: { cover?: string; title: string }, cls = "") {
  const src = String(card.cover || "");
  return `<div class="poster ${cls}"><span class="poster-fallback">${esc(card.title.slice(0, 2))}</span>${src.startsWith("https://") ? `<img src="${esc(src)}" alt="${esc(card.title)}" loading="lazy" referrerpolicy="no-referrer">` : ""}</div>`;
}
function skeleton() {
  return `<div class="cards">${Array.from({ length: 6 }, () => '<div class="skeleton-card"><div></div><span></span><i></i></div>').join("")}</div>`;
}
function renderList() {
  const list = lists[mode];
  const titles = {
    rank: "大家正在追",
    category: "找到你的偏爱",
    latest: "新故事，刚刚上线",
    search: `“${String(list.params.query || "")}”`,
  };
  const subtitles = {
    rank: "从热门好剧开始，发现值得一看的故事。",
    category: "按题材、设定与时代，挑一部合你心意的。",
    latest: "按上架时间排序，下一部好剧就在这里。",
    search: "搜索结果 · 持续加载，发现更多相关剧目",
  };
  workspace.innerHTML = `<section class="page-heading"><div><div class="eyebrow">${{ rank: "THE WATCHLIST", category: "FIND YOUR STORY", latest: "JUST ARRIVED", search: "SEARCH RESULTS" }[mode]}</div><h1>${esc(titles[mode])}<span class="title-dot">.</span></h1><p>${subtitles[mode]}</p></div><div class="heading-decoration" aria-hidden="true">${icon(mode === "rank" ? "rank" : mode === "latest" ? "new" : "search")}</div></section>
    ${filtersHTML(list)}<div class="results-meta"><span>${mode === "rank" ? "人气好剧" : mode === "category" ? "为你发现" : mode === "latest" ? "新鲜上架" : "相关剧目"}</span><span>${list.items.length ? `已展示 ${list.items.length} 部` : "发现值得看的故事"}</span></div>
    ${list.items.length ? `<div class="cards">${list.items.map((card, n) => `<button class="drama-card" data-series="${esc(card.series_id)}" aria-label="查看 ${esc(card.title)} 详情"><div class="poster-wrap">${poster(card)}${mode === "rank" ? `<span class="rank-number ${n < 3 ? "top" : ""}">${String(n + 1).padStart(2, "0")}</span>` : ""}${card.score ? `<span class="score">★ ${esc(card.score)}</span>` : ""}<span class="poster-hover">查看详情 <span>↗</span></span></div><h3>${esc(card.title)}</h3><div class="card-meta"><span>${card.episode_cnt ? `${esc(card.episode_cnt)} 集` : "短剧"}</span><span>查看故事 ↗</span></div></button>`).join("")}</div>` : list.loading ? skeleton() : !list.error ? `<div class="empty-state">${icon("search")}<h3>暂时没有找到剧目</h3><p>换个关键词或筛选条件试试。</p></div>` : ""}
    ${list.warnings.length ? `<div class="notice">${list.warnings.map(esc).join("；")}</div>` : ""}
    ${list.error ? `<div class="error-state"><p>${esc(list.error)}</p><button class="secondary" data-action="load">${icon("refresh")}重新加载</button></div>` : ""}
    <div class="load-zone">${list.loading && list.items.length ? '<span class="spinner"></span><span>正在发现更多好剧…</span>' : list.more ? '<button class="load-more" data-action="load">加载更多 <span>↓</span></button>' : list.items.length && !list.error ? '<span class="end-line"></span><span>已经看到这里的全部剧目</span><span class="end-line"></span>' : ""}</div>`;
}
async function loadList(list = lists[mode]) {
  if (list.loading) return;
  list.loading = true;
  list.error = "";
  if (!detailId && list === lists[mode]) renderKeepScroll();
  try {
    const page = await call<Page>(list.mode, {
      ...list.params,
      cursor: list.cursor,
    });
    const seen = new Set(list.items.map((c) => c.series_id));
    list.items.push(
      ...page.items.filter(
        (c) => !seen.has(c.series_id) && !!seen.add(c.series_id),
      ),
    );
    list.cursor = page.next_cursor;
    list.more = page.has_more;
    list.warnings = page.warnings || [];
    list.loaded = true;
  } catch (error) {
    list.error = String(error);
  } finally {
    list.loading = false;
    if (!detailId && list === lists[mode]) renderKeepScroll();
  }
}
function renderKeepScroll() {
  const y = workspace.scrollTop;
  renderList();
  workspace.scrollTop = y;
}
async function loadFilters(genre: string) {
  const gen = ++filterGeneration;
  filtersLoading = true;
  filtersError = "";
  filtersGenre = genre;
  try {
    const result = await call<{ rows: Filter[] }>("filters", { genre });
    if (gen === filterGeneration) filters = result.rows;
  } catch (error) {
    if (gen === filterGeneration) filtersError = String(error);
  } finally {
    if (gen === filterGeneration) {
      filtersLoading = false;
      if (mode === "category" && !detailId) renderKeepScroll();
    }
  }
}
function navigate(next: Mode) {
  if (!detailId) lists[mode].scroll = workspace.scrollTop;
  mode = next;
  detailId = "";
  detail = null;
  detailGeneration++;
  renderNav();
  renderList();
  workspace.scrollTop = lists[mode].scroll;
  if (mode === "category" && filtersGenre !== lists.category.params.genre)
    void loadFilters(String(lists.category.params.genre));
  if (!lists[mode].loaded && !lists[mode].loading) void loadList();
}
function changeFilter(group: string, value: string) {
  const params = structuredClone(lists[mode].params);
  if (mode === "category" && group !== "genre") {
    const selections = params.selections as Record<string, string[]>;
    const row = filters.find((r) => r.type === group);
    const old = selections[group] || [];
    selections[group] = !value
      ? []
      : row?.selection_type === 1
        ? old.includes(value)
          ? old.filter((v) => v !== value)
          : [...old, value]
        : [value];
  } else {
    params[group] = value;
    if (group === "genre" && mode === "category") {
      params.selections = {};
      void loadFilters(value);
    }
  }
  lists[mode] = blank(mode, params);
  renderList();
  workspace.scrollTop = 0;
  void loadList();
}
async function openDetail(id: string, restore = false) {
  if (!restore) lists[mode].scroll = workspace.scrollTop;
  const gen = ++detailGeneration;
  detailId = id;
  detail = null;
  detailLoading = true;
  detailError = "";
  quality = "1080p";
  episodeRange = 0;
  renderNav();
  renderDetail();
  workspace.scrollTop = 0;
  try {
    const result = await call<Detail>("detail", { series_id: id });
    if (gen === detailGeneration) detail = result;
  } catch (error) {
    if (gen === detailGeneration) detailError = String(error);
  } finally {
    if (gen === detailGeneration) {
      detailLoading = false;
      renderDetail();
    }
  }
}
function renderDetail() {
  const back = `<button class="back" data-action="back">${icon("arrow")}返回${{ rank: "排行榜", category: "分类探索", latest: "最新上架", search: "搜索结果" }[mode]}</button>`;
  if (detailLoading || !detail) {
    workspace.innerHTML = `${back}${detailError ? `<div class="error-state"><h2>暂时无法加载详情</h2><p>${esc(detailError)}</p><button class="secondary" data-action="detail-retry">重试</button></div>` : '<div class="detail-skeleton"><div class="skeleton-card"><div></div></div><div><span class="spinner"></span> 正在打开这个故事…</div></div>'}`;
    return;
  }
  const m = detail.meta;
  workspace.innerHTML = `${back}<section class="detail-hero">${poster(m, "detail-poster")}<div class="detail-copy"><div class="eyebrow">A STORY WORTH KEEPING</div><h1>${esc(m.title)}</h1><div class="detail-tags"><span class="status-pill">${esc(m.status)}</span><span>共 ${esc(m.episode_cnt)} 集</span>${m.score ? `<span class="detail-score">★ ${esc(m.score)}</span>` : ""}</div><p class="intro">${esc(m.intro || "这部剧暂时没有简介。")}</p><span class="series-id">剧目 ID ${esc(detail.series_id)}</span></div></section>
    <section class="episodes-section"><div class="section-title"><div><h2>好故事，现在就看</h2><p>点击播放在线观看，也可以下载一集留在本地。</p></div><label class="quality">清晰度 <select id="quality" aria-label="下载清晰度">${["1080p", "720p", "540p", "480p", "360p"].map((q) => `<option ${q === quality ? "selected" : ""}>${q}</option>`).join("")}</select></label></div>
    ${!detail.complete ? '<div class="notice warning">平台返回的分集信息不完整，下载暂不可用。请重新加载详情。</div>' : ""}
    <div id="episode-tabs"></div><div id="episode-grid"></div></section>`;
  renderEpisodes();
}
function findJob(ep: Episode) {
  return jobs.find(
    (j) =>
      j.series_id === detail?.series_id &&
      j.vid === ep.vid &&
      j.quality === quality,
  );
}
function renderEpisodes() {
  if (!detail || !document.querySelector("#episode-grid")) return;
  document.querySelector("#episode-tabs")!.innerHTML =
    `<div class="episode-ranges">${Array.from({ length: Math.ceil(detail.episodes.length / 30) }, (_, i) => `<button data-range="${i}" class="${episodeRange === i ? "selected" : ""}">${i * 30 + 1}–${Math.min((i + 1) * 30, detail!.episodes.length)} 集</button>`).join("")}</div>`;
  document.querySelector("#episode-grid")!.innerHTML =
    `<div class="episode-grid">${detail.episodes
      .slice(episodeRange * 30, (episodeRange + 1) * 30)
      .map((ep) => {
        const job = findJob(ep),
          busy = job && active.has(job.status),
          done = job?.status === "completed";
        return `<div class="episode"><span class="episode-number">${String(ep.index || "–").padStart(2, "0")}</span><div class="episode-text"><strong>第 ${esc(ep.index)} 集</strong><span>${busy ? labels[job.status] : done ? `${quality} · 已保存` : quality}</span></div><button class="episode-play" data-play="${ep.index}" ${!detail?.complete ? "disabled" : ""} title="播放这一集" aria-label="播放第 ${ep.index} 集">${icon("play")}</button><button class="episode-download ${done ? "done" : ""}" data-episode="${ep.index}" data-view="${busy ? "busy" : done ? "done" : "ready"}" ${!detail?.complete || busy ? "disabled" : ""} title="${done ? "打开所在文件夹" : "下载这一集"}" aria-label="${done ? "打开" : "下载"}第 ${ep.index} 集">${busy ? '<span class="spinner small"></span>' : icon(done ? "folder" : "download")}</button></div>`;
      })
      .join("")}</div>`;
}
function updateEpisodeStatus(job: Job) {
  if (job.series_id !== detail?.series_id || job.quality !== quality) return;
  const ep = detail.episodes.find((e) => e.vid === job.vid);
  if (!ep) return;
  const button = document.querySelector<HTMLButtonElement>(
    `#episode-grid [data-episode="${ep.index}"]`,
  );
  if (!button) return;
  const busy = active.has(job.status),
    done = job.status === "completed";
  button
    .closest(".episode")!
    .querySelector(".episode-text > span")!.textContent = busy
    ? labels[job.status]
    : done
      ? `${quality} · 已保存`
      : quality;
  button.disabled = !detail.complete || busy;
  button.classList.toggle("done", done);
  button.title = done ? "打开所在文件夹" : "下载这一集";
  button.setAttribute(
    "aria-label",
    `${done ? "打开" : "下载"}第 ${ep.index} 集`,
  );
  const view = busy ? "busy" : done ? "done" : "ready";
  if (button.dataset.view !== view) {
    button.dataset.view = view;
    button.innerHTML = busy
      ? '<span class="spinner small"></span>'
      : icon(done ? "folder" : "download");
  }
}
function acceptJob(job: Job) {
  const i = jobs.findIndex((j) => j.id === job.id);
  const previous = jobs[i];
  if (previous && (job.revision || 0) < (previous.revision || 0)) return;
  if (i < 0) jobs.push(job);
  else jobs[i] = job;
  renderTasks();
  if (!previous || previous.status !== job.status) updateEpisodeStatus(job);
}
async function downloadEpisode(index: number) {
  if (!detail) return;
  const ep = detail.episodes.find((e) => e.index === index)!;
  const job = findJob(ep);
  try {
    if (job?.status === "completed") {
      await openJobFolder(job.id);
      return;
    }
    if (job && ["failed", "cancelled", "interrupted"].includes(job.status)) {
      acceptJob(await call<Job>("retry", { id: job.id }));
      toast(`第 ${index} 集已重新加入队列`);
      return;
    }
    const result = await call<Job>("enqueue", {
      series_id: detail.series_id,
      index,
      quality,
    });
    acceptJob(result);
    toast(
      result.status === "failed"
        ? result.error
        : `第 ${index} 集已加入下载队列`,
    );
  } catch (error) {
    toast(String(error));
  }
}
async function openJobFolder(id: string) {
  const result = await call<{ path: string }>("folder", { id });
  await invoke("open_directory", { path: result.path });
}
function closePlayer(restoreFocus = true) {
  const state = player?.state;
  player?.cancelBuffering?.();
  player = null;
  const video = document.querySelector<HTMLVideoElement>("#episode-video");
  if (video) {
    video.pause();
    video.removeAttribute("src");
    video.load();
  }
  document.querySelector("#player-root")!.innerHTML = "";
  if (state?.id) void call("playback_close", { id: state.id }).catch(() => {});
  if (restoreFocus) {
    if (playerFocus?.isConnected) playerFocus.focus();
    playerFocus = null;
  }
}
function playerMessage(message: string) {
  const status = document.querySelector("#player-status");
  if (status && status.textContent !== message) status.textContent = message;
}
function playerFailure(message: string) {
  if (!player) return;
  player.cancelBuffering?.();
  player.mediaError = message;
  playerMessage(message);
  document.querySelector(".player-stage")?.classList.remove("loading");
  const retry = document.querySelector<HTMLButtonElement>("#player-retry");
  if (retry) retry.hidden = false;
}
function acceptPlayback(state: Playback) {
  if (!player || state.request_id !== player.requestId) return;
  if (player.state && state.revision < player.state.revision) return;
  player.state = state;
  const source = document.querySelector<HTMLElement>("#player-source")!;
  source.textContent = state.model_api
    ? `${state.model_api}${state.model_fallback ? " · 已回退" : ""}`
    : "";
  source.title = state.model_fallback_reason || "";
  if (state.status === "failed") {
    document.querySelector<HTMLVideoElement>("#episode-video")?.pause();
    playerFailure(state.error || "暂时无法播放，请重试");
    return;
  }
  if (state.status === "preparing") {
    playerMessage(`${state.phase}…`);
    return;
  }
  const video = document.querySelector<HTMLVideoElement>("#episode-video")!;
  if (state.url && video.getAttribute("src") !== state.url) {
    video.src = state.url;
    playerMessage("正在缓冲…");
    void video.play().catch((error: DOMException) => {
      if (!player || player.requestId !== state.request_id) return;
      if (error.name === "NotAllowedError") {
        player.cancelBuffering?.();
        document.querySelector(".player-stage")?.classList.remove("loading");
        playerMessage("视频已就绪，点击画面中的播放按钮开始");
      }
    });
  }
}
async function openPlayer(
  index: number,
  drama = detail,
  selectedQuality = quality,
) {
  if (!drama?.complete || !drama.episodes.some((ep) => ep.index === index))
    return;
  if (!playerFocus) playerFocus = document.activeElement as HTMLElement;
  closePlayer(false);
  const requestId = crypto.randomUUID();
  player = { requestId, detail: drama, index, quality: selectedQuality };
  const position = drama.episodes.findIndex((ep) => ep.index === index);
  document.querySelector("#player-root")!.innerHTML = `
    <div class="player-backdrop"><section class="player-dialog" role="dialog" aria-modal="true" aria-labelledby="player-title">
      <header class="player-header"><div><span class="eyebrow">正在观看 · 第 ${esc(index)} 集</span><h2 id="player-title">${esc(drama.meta.title)}</h2></div><button class="player-close" data-action="close-player" aria-label="关闭播放器">${icon("close")}</button></header>
      <div class="player-stage loading"><video id="episode-video" controls playsinline preload="metadata" aria-label="第 ${esc(index)} 集视频"></video><div class="player-loading"><span class="spinner"></span><span>正在准备这个故事</span></div></div>
      <div class="player-status-line"><span id="player-status" role="status">获取视频…</span><button id="player-retry" class="secondary" data-action="retry-player" hidden>重试播放</button><small id="player-source"></small></div>
      <footer class="player-controls"><div class="player-paging"><button class="secondary" data-player-step="-1" ${position === 0 ? "disabled" : ""}>上一集</button><label class="player-select">选集 <select id="player-episode" aria-label="播放分集">${drama.episodes.map((ep) => `<option value="${ep.index}" ${ep.index === index ? "selected" : ""}>第 ${ep.index} 集</option>`).join("")}</select></label><button class="secondary" data-player-step="1" ${position === drama.episodes.length - 1 ? "disabled" : ""}>下一集</button></div><label class="player-select">清晰度 <select id="player-quality" aria-label="播放清晰度">${["1080p", "720p", "540p", "480p", "360p"].map((q) => `<option ${q === selectedQuality ? "selected" : ""}>${q}</option>`).join("")}</select></label></footer>
    </section></div>`;
  const video = document.querySelector<HTMLVideoElement>("#episode-video")!;
  const stage = document.querySelector<HTMLElement>(".player-stage")!;
  let bufferingTimer: number | undefined;
  const cancelBuffering = () => {
    window.clearTimeout(bufferingTimer);
    bufferingTimer = undefined;
  };
  player.cancelBuffering = cancelBuffering;
  const valid = () =>
    player?.requestId === requestId &&
    player.state?.status === "ready" &&
    !player.mediaError;
  for (const name of [
    "loadeddata",
    "canplay",
    "playing",
    "pause",
    "waiting",
    "seeking",
    "seeked",
    "ended",
  ]) {
    video.addEventListener(name, () => {
      if (!valid()) return;
      // The full overlay belongs to initial loading only. Seeking keeps the
      // decoded frame visible; a brief wait should not flash any loading UI.
      if (["waiting", "seeking"].includes(name)) {
        if (bufferingTimer === undefined) {
          bufferingTimer = window.setTimeout(() => {
            if (valid()) playerMessage("正在缓冲…");
          }, 300);
        }
        return;
      }
      cancelBuffering();
      if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA)
        stage.classList.remove("loading");
      playerMessage(
        video.ended
          ? "本集已播完，可以继续下一集"
          : video.paused
            ? "已暂停"
            : "正在播放",
      );
    });
  }
  video.addEventListener("error", () => {
    if (
      player?.requestId !== requestId ||
      !video.getAttribute("src") ||
      player.state?.status === "failed"
    )
      return;
    playerFailure(
      video.error?.code === 4
        ? "当前系统无法播放此视频编码，可尝试其他清晰度"
        : "视频读取或解码失败，请重试播放",
    );
  });
  document.querySelector<HTMLButtonElement>(".player-close")!.focus();
  try {
    const state = await call<Playback>("playback_open", {
      series_id: drama.series_id,
      index,
      quality: selectedQuality,
      request_id: requestId,
    });
    if (player?.requestId !== requestId) {
      void call("playback_close", { id: state.id }).catch(() => {});
      return;
    }
    acceptPlayback(state);
  } catch (error) {
    if (player?.requestId === requestId) playerFailure(String(error));
  }
}
function updateTaskCard(card: HTMLElement, job: Job) {
  const status = card.querySelector<HTMLElement>(".task-status")!;
  const label = status.querySelector("span")!;
  const button = status.querySelector("button")!;
  const busy = active.has(job.status),
    done = job.status === "completed";
  const statusText = `${labels[job.status] || job.status}${job.status === "downloading" ? ` · ${job.progress.toFixed(0)}%` : ""}`;
  if (card.dataset.status !== job.status || label.textContent !== statusText) {
    label.innerHTML = `${done ? icon("check") : ""}${esc(statusText)}`;
  }
  card.dataset.status = job.status;
  status.className = `task-status ${job.status}`;
  const action = busy ? "cancel" : done ? "folder" : "retry";
  if (button.dataset.jobAction !== action) {
    button.dataset.jobAction = action;
    button.textContent = busy ? "取消" : done ? "打开文件夹 ↗" : "重试";
  }
  button.disabled = job.status === "cancelling";
  const source = card.querySelector<HTMLElement>(".model-source")!;
  const knownAPI =
    job.model_api === "multi_video_model" || job.model_api === "video_model";
  let sourceText = active.has(job.status)
    ? "模型接口：待请求"
    : "模型接口：未记录";
  if (job.model_api === "local") sourceText = "本地已校验 · 无接口请求";
  else if (knownAPI) {
    const suffix =
      job.model_api_state === "requesting"
        ? job.model_fallback
          ? "回退请求中"
          : "请求中"
        : job.model_api_state === "failed"
          ? job.model_fallback
            ? "回退失败"
            : "请求失败"
          : job.model_fallback
            ? "已回退"
            : "";
    sourceText = `${job.model_api}${suffix ? ` · ${suffix}` : ""}`;
  }
  if (source.textContent !== sourceText) source.textContent = sourceText;
  source.title = knownAPI
    ? `/novel/player/${job.model_api}/v1/${job.model_fallback_reason ? `\n批量接口未取得模型：${job.model_fallback_reason}` : ""}`
    : job.model_api === "local"
      ? "复用已校验的本地成品，没有发起模型接口请求"
      : active.has(job.status)
        ? "轮到该任务执行时才请求视频模型"
        : "此历史任务未保存模型接口来源";
  let progress = card.querySelector<HTMLElement>(".progress");
  if (busy) {
    if (!progress) {
      progress = document.createElement("div");
      progress.className = "progress";
      progress.append(document.createElement("span"));
      status.after(progress);
    }
    progress.classList.toggle(
      "processing",
      job.status === "verifying" || job.status === "decrypting",
    );
    const bar = progress.firstElementChild as HTMLElement;
    const width = `${job.status === "queued" ? 0 : Math.max(3, job.progress)}%`;
    if (bar.style.width !== width) bar.style.width = width;
  } else progress?.remove();
  let error = card.querySelector<HTMLElement>(".task-error");
  if (job.error) {
    if (!error) {
      error = document.createElement("p");
      error.className = "task-error";
      card.append(error);
    }
    if (error.textContent !== job.error) error.textContent = job.error;
  } else error?.remove();
}
function renderTasks() {
  const count = jobs.filter((j) => active.has(j.status)).length;
  document.querySelector("#task-count")!.textContent = String(count);
  document.querySelector("#task-count")!.classList.toggle("running", count > 0);
  const root = document.querySelector("#drawer-root")!;
  if (!drawer) {
    if (root.hasChildNodes()) root.replaceChildren();
    return;
  }
  // Mount once per opening. Progress must not recreate the drawer, replay its
  // entrance animation, reset a spinner or steal focus from the cancel button.
  if (!root.querySelector(".drawer")) {
    root.innerHTML = `<div class="drawer-backdrop" data-action="close-drawer"></div><aside class="drawer" aria-label="下载任务"><div class="drawer-heading"><div><div class="eyebrow">YOUR COLLECTION</div><h2>下载任务 <span></span></h2></div><button class="icon-button" data-action="close-drawer" aria-label="关闭任务面板">${icon("close")}</button></div><div class="queue-summary"><i></i><span></span></div><div class="task-list"></div><div class="drawer-footer"><span>保存位置</span><button data-action="location">${icon("folder")}<span></span><b>更改</b></button></div></aside>`;
  }
  const setText = (selector: string, text: string) => {
    const element = root.querySelector(selector)!;
    if (element.textContent !== text) element.textContent = text;
  };
  setText(".drawer-heading h2 span", String(jobs.length));
  setText(
    ".queue-summary > span",
    count ? `${count} 个任务进行中，按顺序下载` : "下载完成后，好故事随时可看",
  );
  root
    .querySelector(".queue-summary > i")!
    .classList.toggle("pulse", count > 0);
  setText(".drawer-footer button span", directory || "正在读取…");
  const list = root.querySelector<HTMLElement>(".task-list")!;
  const scroll = list.scrollTop;
  if (!jobs.length) {
    if (!list.querySelector(".empty-state"))
      list.innerHTML = `<div class="empty-state">${icon("download")}<h3>还没有下载任务</h3><p>打开一部剧的详情，<br>选择喜欢的一集开始保存。</p></div>`;
    return;
  }
  list.querySelector(".empty-state")?.remove();
  const cards = new Map(
    Array.from(list.querySelectorAll<HTMLElement>(".task-card"), (card) => [
      card.dataset.taskId!,
      card,
    ]),
  );
  [...jobs].reverse().forEach((job, index) => {
    let card = cards.get(job.id);
    if (!card) {
      card = document.createElement("article");
      card.className = "task-card";
      card.dataset.taskId = job.id;
      card.innerHTML = `<div class="task-top"><span class="task-episode">${String(job.index).padStart(2, "0")}</span><div><h3>${esc(job.title)}</h3><span>第 ${job.index} 集 · ${esc(job.quality)}</span></div></div><div class="task-status"><div class="task-state"><span class="task-state-label"></span><small class="model-source"></small></div><div><button data-job="${esc(job.id)}"></button></div></div>`;
    }
    if (list.children[index] !== card)
      list.insertBefore(card, list.children[index] || null);
    updateTaskCard(card, job);
    cards.delete(job.id);
  });
  for (const card of cards.values()) card.remove();
  list.scrollTop = scroll;
}
async function chooseLocation() {
  try {
    const result = await invoke<string | null>("choose_directory");
    if (result) {
      const saved = await call<{ directory: string }>("settings", {
        directory: result,
      });
      directory = saved.directory;
      renderLocation();
      renderTasks();
      toast("新的下载任务将保存到所选文件夹");
    }
  } catch (error) {
    toast(String(error));
  }
}
function renderLocation() {
  const el = document.querySelector<HTMLElement>("#save-location")!;
  el.title = `更改下载位置：${directory}`;
  document.querySelector("#location-label")!.textContent = directory
    ? directory.replace(/^\/Users\/[^/]+/, "~")
    : "下载位置";
}
async function requestQuit() {
  if (quitting) return;
  const pendingAtRequest = pendingDownloads > 0;
  try {
    jobs = (await call<{ jobs: Job[] }>("state")).jobs;
  } catch {
    /* Allow exit if the worker is unavailable. */
  }
  if (
    !pendingAtRequest &&
    pendingDownloads === 0 &&
    !jobs.some((j) => active.has(j.status))
  ) {
    await quit();
    return;
  }
  document.querySelector("#modal-root")!.innerHTML =
    `<div class="modal-backdrop"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="quit-title"><div class="modal-icon">${icon("download")}</div><h2 id="quit-title">下载尚未完成</h2><p>退出将停止当前任务。下次打开后，你可以手动重试，未完成的这一集会从头下载。</p><div class="modal-actions"><button class="secondary" data-action="keep-open">继续下载</button><button class="primary" data-action="quit">停止并退出</button></div></section></div>`;
  document
    .querySelector<HTMLButtonElement>('[data-action="keep-open"]')
    ?.focus();
}
async function quit() {
  quitting = true;
  closePlayer(false);
  document.querySelector("#modal-root")!.innerHTML =
    '<div class="modal-backdrop"><section class="modal"><span class="spinner"></span><h2>正在安全退出</h2><p>保存任务记录并停止后台进程…</p></section></div>';
  await invoke("quit_app");
}

document.querySelector("#search-form")!.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = document
    .querySelector<HTMLInputElement>("#query")!
    .value.trim();
  if (!query) {
    document.querySelector<HTMLInputElement>("#query")!.focus();
    return;
  }
  lists.search = blank("search", { query });
  navigate("search");
});
document
  .querySelector("#home")!
  .addEventListener("click", () => navigate("rank"));
document.querySelector("#tasks")!.addEventListener("click", () => {
  drawer = !drawer;
  renderTasks();
});
document
  .querySelector("#save-location")!
  .addEventListener("click", () => void chooseLocation());
document.addEventListener("change", (event) => {
  if ((event.target as HTMLElement).id === "quality") {
    quality = (event.target as HTMLSelectElement).value;
    renderEpisodes();
  } else if ((event.target as HTMLElement).id === "player-quality" && player) {
    void openPlayer(
      player.index,
      player.detail,
      (event.target as HTMLSelectElement).value,
    );
  } else if ((event.target as HTMLElement).id === "player-episode" && player) {
    void openPlayer(
      Number((event.target as HTMLSelectElement).value),
      player.detail,
      player.quality,
    );
  }
});
document.addEventListener(
  "error",
  (event) => {
    if (event.target instanceof HTMLImageElement)
      event.target.style.display = "none";
  },
  true,
);
document.addEventListener("click", async (event) => {
  const button = (event.target as Element).closest<HTMLElement>("button");
  if (!button || button.hasAttribute("disabled")) return;
  const d = button.dataset;
  if (d.mode) navigate(d.mode as Mode);
  else if (d.group) changeFilter(d.group, d.value || "");
  else if (d.series) void openDetail(d.series);
  else if (d.play) void openPlayer(Number(d.play));
  else if (d.action === "close-player") closePlayer();
  else if (d.action === "retry-player" && player)
    void openPlayer(player.index, player.detail, player.quality);
  else if (d.playerStep && player) {
    const position = player.detail.episodes.findIndex(
      (ep) => ep.index === player!.index,
    );
    const next = player.detail.episodes[position + Number(d.playerStep)];
    if (next) void openPlayer(next.index, player.detail, player.quality);
  } else if (d.episode) void downloadEpisode(Number(d.episode));
  else if (d.range !== undefined) {
    episodeRange = Number(d.range);
    renderEpisodes();
  } else if (d.job) {
    try {
      if (d.jobAction === "folder") await openJobFolder(d.job);
      else acceptJob(await call<Job>(d.jobAction!, { id: d.job }));
    } catch (error) {
      toast(String(error));
    }
  } else if (d.action === "back") navigate(mode);
  else if (d.action === "load") void loadList();
  else if (d.action === "filter-retry")
    void loadFilters(String(lists.category.params.genre));
  else if (d.action === "expand-filters") {
    expandedFilters = !expandedFilters;
    renderKeepScroll();
  } else if (d.action === "detail-retry") void openDetail(detailId, true);
  else if (d.action === "close-drawer") {
    drawer = false;
    renderTasks();
  } else if (d.action === "location") void chooseLocation();
  else if (d.action === "keep-open")
    document.querySelector("#modal-root")!.innerHTML = "";
  else if (d.action === "quit") void quit();
});
document.querySelector("#drawer-root")!.addEventListener("click", (event) => {
  if ((event.target as HTMLElement).classList.contains("drawer-backdrop")) {
    drawer = false;
    renderTasks();
  }
});
document.addEventListener("keydown", (event) => {
  if (player && !document.querySelector("#modal-root > *")) {
    if (event.key === "Escape") {
      event.preventDefault();
      closePlayer();
    } else if (event.key === "Tab") {
      const focusable = Array.from(
        document.querySelectorAll<HTMLElement>(
          "#player-root button:not(:disabled):not([hidden]), #player-root select, #player-root video",
        ),
      );
      const first = focusable[0],
        last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    return;
  }
  if ((event.metaKey || event.ctrlKey) && event.key === "f") {
    event.preventDefault();
    document.querySelector<HTMLInputElement>("#query")!.focus();
  }
  if (event.key === "Escape") {
    if (drawer) {
      drawer = false;
      renderTasks();
    } else if (!quitting) document.querySelector("#modal-root")!.innerHTML = "";
  }
});
async function start() {
  renderNav();
  renderList();
  try {
    await listen<{ event: string; job?: Job; playback?: Playback }>(
      "backend-event",
      ({ payload }) => {
        if (payload.job) acceptJob(payload.job);
        if (payload.playback) acceptPlayback(payload.playback);
        if (payload.event === "disconnected" && player)
          playerFailure("后台进程已退出，请重新启动应用");
        if (payload.event === "disconnected" && !quitting)
          toast("后台进程已退出，请重新启动应用。");
      },
    );
    await listen("exit-request", () => void requestQuit());
    const state = await call<{ settings: { directory: string }; jobs: Job[] }>(
      "state",
    );
    // Merge after listener registration so early progress cannot get overwritten.
    directory = state.settings.directory;
    jobs = [
      ...state.jobs.filter((j) => !jobs.some((x) => x.id === j.id)),
      ...jobs,
    ];
    renderLocation();
    renderTasks();
    void loadList();
  } catch (error) {
    lists.rank.error = String(error);
    renderList();
  }
}
void start();
