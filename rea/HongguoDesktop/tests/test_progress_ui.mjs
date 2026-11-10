import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

const source = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
// Exercise the production entry point and event handlers, replacing only the
// native IPC imports and stylesheet import in this DOM regression harness.
const script = ts.transpileModule(source.replace(/^import .*;\n/gm, ""), {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.None,
  },
}).outputText;
const flush = () => new Promise((resolve) => setImmediate(resolve));

async function screen(t, onPlaybackOpen) {
  const dom = new JSDOM('<!doctype html><div id="app"></div>', {
    runScripts: "outside-only",
    url: "http://localhost/",
  });
  t.after(() => dom.window.close());
  dom.window.HTMLMediaElement.prototype.play = async function () {};
  dom.window.HTMLMediaElement.prototype.pause = function () {};
  dom.window.HTMLMediaElement.prototype.load = function () {};
  const events = new Map();
  const calls = [];
  const jobs = Array.from({ length: 6 }, (_, i) => ({
    id: `job-${i + 1}`,
    series_id: "series",
    title: "测试剧",
    vid: `vid-${i + 1}`,
    index: i + 1,
    quality: "1080p",
    status: i ? "queued" : "downloading",
    progress: i ? 0 : 20,
    file: "",
    error: "",
    revision: 1,
  }));
  const card = {
    series_id: "series",
    title: "测试剧",
    cover: "",
    episode_cnt: 60,
    score: "",
  };
  dom.window.listen = async (name, callback) => {
    events.set(name, callback);
    return () => events.delete(name);
  };
  dom.window.invoke = async (command, args = {}) => {
    calls.push({ command, ...args });
    if (command !== "backend_call") return null;
    if (args.method === "state")
      return {
        settings: { directory: "/test/downloads" },
        jobs: structuredClone(jobs),
      };
    if (args.method === "rank")
      return { items: [card], has_more: false, next_cursor: null };
    if (args.method === "detail")
      return {
        series_id: "series",
        meta: { ...card, intro: "测试简介", status: "已完结" },
        complete: true,
        issues: [],
        episodes: Array.from({ length: 60 }, (_, i) => ({
          index: i + 1,
          vid: `vid-${i + 1}`,
          title: "",
        })),
      };
    if (args.method === "cancel")
      return {
        ...jobs.find((j) => j.id === args.params.id),
        status: "cancelled",
        revision: 100,
      };
    if (args.method === "folder") return { path: "/test/downloads/测试剧" };
    if (args.method === "playback_open") {
      if (onPlaybackOpen) return onPlaybackOpen(args.params);
      return {
        id: `play-${args.params.index}`,
        request_id: args.params.request_id,
        status: "preparing",
        phase: "获取视频",
        revision: 0,
      };
    }
    if (args.method === "playback_close") return { closed: true };
    throw new Error(`Unexpected IPC ${args.method}`);
  };
  dom.window.eval(script);
  await flush();
  const document = dom.window.document;
  document.querySelector('[data-series="series"]').click();
  await flush();
  document.querySelector("#tasks").click();
  return {
    document,
    jobs,
    calls,
    emit: (job) =>
      events.get("backend-event")({ payload: { event: "job", job } }),
    emitPlayback: (playback) =>
      events.get("backend-event")({ payload: { event: "playback", playback } }),
  };
}

test("playback starts on demand, retains video on task updates, switches episodes and closes", async (t) => {
  const { document: d, calls, jobs, emit, emitPlayback } = await screen(t);
  assert.equal(calls.filter((c) => c.method === "playback_open").length, 0);
  const opener = d.querySelector('[data-play="1"]');
  opener.focus();
  opener.click();
  await flush();
  const first = calls.find((c) => c.method === "playback_open").params;
  const ready = {
    id: "play-1",
    request_id: first.request_id,
    status: "ready",
    phase: "就绪",
    revision: 4,
    url: "http://127.0.0.1:12345/media/one.mp4",
    model_api: "video_model",
    model_fallback: true,
  };
  emitPlayback(ready);
  const video = d.querySelector("#episode-video");
  video.currentTime = 17;
  emit({ ...jobs[0], progress: 42, revision: 2 });
  emitPlayback({ ...ready, revision: 0, status: "preparing" });
  assert.equal(d.querySelector("#episode-video"), video);
  assert.equal(video.currentTime, 17);
  assert.equal(video.getAttribute("src"), ready.url);
  assert.match(d.querySelector("#player-source").textContent, /已回退/);
  d.querySelector('[data-player-step="1"]').click();
  await flush();
  const second = calls
    .filter((c) => c.method === "playback_open")
    .at(-1).params;
  assert.equal(second.index, 2);
  assert.ok(
    calls.some(
      (c) => c.method === "playback_close" && c.params.id === "play-1",
    ),
  );
  emitPlayback(ready);
  assert.equal(d.querySelector("#episode-video").getAttribute("src"), null);
  d.querySelector('[data-action="close-player"]').click();
  await flush();
  assert.equal(d.querySelector("#episode-video"), null);
  assert.equal(d.activeElement, opener);
  assert.ok(
    calls.some(
      (c) => c.method === "playback_close" && c.params.id === "play-2",
    ),
  );
  assert.ok(!calls.some((c) => c.method === "enqueue"));
});

test("closing while preparation is pending cancels its late reply without reopening", async (t) => {
  let resolve, parameters;
  const { document: d, calls } = await screen(t, (params) => {
    parameters = params;
    return new Promise((done) => {
      resolve = done;
    });
  });
  d.querySelector('[data-play="1"]').click();
  await flush();
  d.querySelector('[data-action="close-player"]').click();
  resolve({
    id: "late",
    request_id: parameters.request_id,
    status: "preparing",
    phase: "获取视频",
    revision: 0,
  });
  await flush();
  assert.equal(d.querySelector("#episode-video"), null);
  assert.ok(
    calls.some((c) => c.method === "playback_close" && c.params.id === "late"),
  );
});

test("seeking after the first frame never flashes the startup overlay or reloads the player", async (t) => {
  const { document: d, calls, emitPlayback } = await screen(t);
  d.querySelector('[data-play="1"]').click();
  await flush();
  const request = calls.find((c) => c.method === "playback_open").params;
  emitPlayback({
    id: "play-1",
    request_id: request.request_id,
    status: "ready",
    phase: "就绪",
    revision: 4,
    url: "http://127.0.0.1:12345/media/one.mp4",
  });
  const video = d.querySelector("#episode-video");
  const dialog = d.querySelector(".player-dialog");
  const stage = d.querySelector(".player-stage");
  const dispatch = (name) => video.dispatchEvent(new d.defaultView.Event(name));
  Object.defineProperty(video, "paused", { value: false, configurable: true });
  Object.defineProperty(video, "readyState", { value: 4, configurable: true });
  dispatch("loadeddata");
  dispatch("playing");
  assert.equal(stage.classList.contains("loading"), false);
  const url = video.getAttribute("src");
  const callsBeforeSeeking = calls.length;
  for (let attempt = 0; attempt < 3; attempt++) {
    video.currentTime = 30 + attempt;
    dispatch("seeking");
    assert.equal(
      stage.classList.contains("loading"),
      false,
      "seek must not cover the visible frame",
    );
    dispatch("waiting");
    assert.equal(
      stage.classList.contains("loading"),
      false,
      "buffering must not cover the visible frame",
    );
    assert.equal(
      d.querySelector("#player-status").textContent,
      "正在播放",
      "brief seeks must not flash a buffering message",
    );
    dispatch("seeked");
    dispatch("playing");
    assert.equal(d.querySelector("#episode-video"), video);
    assert.equal(d.querySelector(".player-dialog"), dialog);
    assert.equal(video.getAttribute("src"), url);
    assert.equal(video.currentTime, 30 + attempt);
  }
  assert.equal(calls.length, callsBeforeSeeking);
});

test("long buffering only updates the status and pending hints are cancelled on recovery, failure and close", async (t) => {
  const { document: d, calls, emitPlayback } = await screen(t);
  d.querySelector('[data-play="1"]').click();
  await flush();
  const request = calls.find((c) => c.method === "playback_open").params;
  const ready = {
    id: "play-1",
    request_id: request.request_id,
    status: "ready",
    phase: "就绪",
    revision: 4,
    url: "http://127.0.0.1:12345/media/one.mp4",
  };
  emitPlayback(ready);
  const video = d.querySelector("#episode-video");
  const stage = d.querySelector(".player-stage");
  const status = d.querySelector("#player-status");
  const win = d.defaultView;
  const pending = new Map();
  let now = 0,
    timerId = 0;
  win.setTimeout = (callback, delay) => {
    const id = ++timerId;
    pending.set(id, { callback, due: now + delay });
    return id;
  };
  win.clearTimeout = (id) => pending.delete(id);
  const advance = (ms) => {
    now += ms;
    for (const [id, timer] of pending) {
      if (timer.due <= now) {
        pending.delete(id);
        timer.callback();
      }
    }
  };
  const dispatch = (name) => video.dispatchEvent(new win.Event(name));
  assert.equal(
    stage.classList.contains("loading"),
    true,
    "initial preparation still has its loading indicator",
  );
  Object.defineProperty(video, "paused", { value: false, configurable: true });
  Object.defineProperty(video, "readyState", { value: 4, configurable: true });
  dispatch("loadeddata");
  dispatch("playing");
  dispatch("seeking");
  dispatch("waiting");
  advance(100);
  assert.equal(status.textContent, "正在播放");
  dispatch("seeked");
  dispatch("playing");
  advance(1000);
  assert.equal(status.textContent, "正在播放");
  dispatch("waiting");
  advance(1000);
  assert.equal(status.textContent, "正在缓冲…");
  assert.equal(stage.classList.contains("loading"), false);
  dispatch("canplay");
  assert.equal(status.textContent, "正在播放");
  Object.defineProperty(video, "paused", { value: true, configurable: true });
  dispatch("seeking");
  dispatch("seeked");
  advance(1000);
  assert.equal(status.textContent, "已暂停");
  dispatch("waiting");
  emitPlayback({
    ...ready,
    status: "failed",
    error: "测试连接中断",
    revision: 5,
  });
  advance(1000);
  assert.equal(status.textContent, "测试连接中断");
  assert.equal(pending.size, 0);
  d.querySelector('[data-action="retry-player"]').click();
  await flush();
  const nextRequest = calls
    .filter((c) => c.method === "playback_open")
    .at(-1).params;
  emitPlayback({ ...ready, request_id: nextRequest.request_id });
  const nextVideo = d.querySelector("#episode-video");
  nextVideo.dispatchEvent(new win.Event("waiting"));
  d.querySelector('[data-action="close-player"]').click();
  advance(1000);
  assert.equal(pending.size, 0);
  assert.equal(d.querySelector("#episode-video"), null);
});

test("browsing and opening the task panel never request video models", async (t) => {
  const { calls } = await screen(t);
  assert.deepEqual(
    calls.filter((c) => c.command === "backend_call").map((c) => c.method),
    ["state", "rank", "detail"],
  );
});

test("model source shows primary, fallback and completion without rebuilding the card", async (t) => {
  const { document: d, jobs, emit } = await screen(t);
  const card = d.querySelector('[data-job="job-1"]').closest(".task-card");
  const badge = card.querySelector(".model-source");
  emit({
    ...jobs[0],
    status: "preparing",
    model_api: "multi_video_model",
    model_api_state: "requesting",
    model_fallback: false,
    revision: 2,
  });
  assert.equal(badge.textContent, "multi_video_model · 请求中");
  const fallback = {
    model_api: "video_model",
    model_fallback: true,
    model_fallback_reason: "Code=110001",
  };
  emit({
    ...jobs[0],
    ...fallback,
    status: "preparing",
    model_api_state: "requesting",
    revision: 3,
  });
  assert.equal(badge.textContent, "video_model · 回退请求中");
  assert.match(badge.title, /110001/);
  for (const [i, status] of [
    "downloading",
    "decrypting",
    "completed",
  ].entries()) {
    emit({
      ...jobs[0],
      ...fallback,
      status,
      model_api_state: "selected",
      revision: i + 4,
    });
    assert.equal(
      d.querySelector('[data-job="job-1"]').closest(".task-card"),
      card,
    );
    assert.equal(card.querySelector(".model-source"), badge);
    assert.equal(badge.textContent, "video_model · 已回退");
  }
  emit({
    ...jobs[0],
    status: "completed",
    model_api: "local",
    model_api_state: "cached",
    revision: 8,
  });
  assert.equal(badge.textContent, "本地已校验 · 无接口请求");
});

test("progress events preserve drawer, animation nodes, scroll and focused controls", async (t) => {
  const { document: d, jobs, emit } = await screen(t);
  const drawer = d.querySelector(".drawer");
  const list = d.querySelector(".task-list");
  const button = d.querySelector('[data-job="job-1"]');
  const card = button.closest(".task-card");
  const bar = card.querySelector(".progress > span");
  const episodes = d.querySelector(".episode-grid");
  const spinner = d.querySelector('[data-episode="1"] .spinner');
  const range = d.querySelector('[data-range="1"]');
  list.scrollTop = 180;
  button.focus();
  for (const [index, progress] of [21, 35, 52, 73, 99].entries()) {
    emit({ ...jobs[0], progress, revision: index + 2 });
    assert.equal(
      d.querySelector(".drawer"),
      drawer,
      "progress must not recreate the drawer and restart its entrance animation",
    );
    assert.equal(d.querySelector(".task-list"), list);
    assert.equal(list.scrollTop, 180);
    assert.equal(
      d.activeElement,
      button,
      "cancel button must keep keyboard focus",
    );
    assert.equal(
      card.querySelector(".progress > span"),
      bar,
      "progress width must animate on the existing bar",
    );
    assert.equal(bar.style.width, `${progress}%`);
    assert.match(
      card.querySelector(".task-status").textContent,
      new RegExp(`${progress}%`),
    );
    assert.equal(
      d.querySelector(".episode-grid"),
      episodes,
      "progress must not rebuild the episode grid",
    );
    assert.equal(d.querySelector('[data-episode="1"] .spinner'), spinner);
    assert.equal(d.querySelector('[data-range="1"]'), range);
  }
  emit({ ...jobs[0], progress: 5, revision: 1 });
  assert.equal(
    bar.style.width,
    "99%",
    "stale events must not roll back progress",
  );
});

test("status transitions and new tasks update in place and retain working actions", async (t) => {
  const { document: d, jobs, emit, calls } = await screen(t);
  const drawer = d.querySelector(".drawer");
  const list = d.querySelector(".task-list");
  const card = d.querySelector('[data-job="job-1"]').closest(".task-card");
  const untouched = d.querySelector('[data-episode="2"]');
  for (const [i, status] of [
    "decrypting",
    "verifying",
    "completed",
  ].entries()) {
    emit({ ...jobs[0], status, progress: 100, revision: i + 2 });
    assert.equal(d.querySelector(".drawer"), drawer);
    assert.equal(
      d.querySelector('[data-job="job-1"]').closest(".task-card"),
      card,
    );
    assert.equal(d.querySelector('[data-episode="2"]'), untouched);
  }
  assert.equal(card.querySelector(".progress"), null);
  assert.equal(card.querySelector("button").dataset.jobAction, "folder");
  assert.match(
    d.querySelector('[data-episode="1"]').getAttribute("aria-label"),
    /打开/,
  );
  card.querySelector("button").click();
  await flush();
  assert.ok(calls.some((c) => c.command === "open_directory"));
  emit({ ...jobs[1], id: "job-new", vid: "vid-7", index: 7, revision: 1 });
  assert.equal(d.querySelector(".task-list"), list);
  assert.equal(
    list.firstElementChild.querySelector("button").dataset.job,
    "job-new",
  );
  assert.equal(d.querySelectorAll(".task-card").length, 7);
  d.querySelector('[data-job="job-2"]').click();
  await flush();
  assert.equal(
    d.querySelector('[data-job="job-2"]').dataset.jobAction,
    "retry",
  );
  assert.equal(d.querySelector('[data-episode="2"]').disabled, false);
  d.querySelector('[data-action="close-drawer"]').click();
  assert.equal(d.querySelector(".drawer"), null);
  d.querySelector("#tasks").click();
  assert.equal(d.querySelectorAll(".task-card").length, 7);
});
