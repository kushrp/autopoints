(function () {
  'use strict';

  // ===== State =====

  const STORAGE_KEY = 'autopoints.onboard.v1';

  const defaultState = () => ({
    step: 1,
    mode: null, // 'local' | 'nas'
    services: {
      web: true,
      discord: false,
      autoruns: false,
    },
    discord: {
      token: '',
      guild_id: '',
      notify_channel_id: '',
      run_interval_minutes: 60,
      demo_mode: false,
      tested_ok: false,
      bot_username: null,
    },
    watchlists: [], // array of staged watchlist objects
    step5: {
      activeTemplate: null, // 'holiday' | 'custom' | 'skip' | null
    },
  });

  function loadState() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return defaultState();
      const parsed = JSON.parse(raw);
      return Object.assign(defaultState(), parsed, {
        services: Object.assign(defaultState().services, parsed.services || {}),
        discord: Object.assign(defaultState().discord, parsed.discord || {}),
        step5: Object.assign(defaultState().step5, parsed.step5 || {}),
        watchlists: Array.isArray(parsed.watchlists) ? parsed.watchlists : [],
      });
    } catch (_) {
      return defaultState();
    }
  }

  function saveState() {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (_) {
      // ignore
    }
  }

  const state = loadState();

  // ===== DOM helpers =====

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const stepSections = {};
  $$('.wizard-step').forEach((el) => {
    stepSections[el.dataset.step] = el;
  });

  const progressSteps = {};
  $$('.wizard-progress-step').forEach((el) => {
    progressSteps[el.dataset.step] = el;
  });

  // Step 4 is conditional: skipped if Discord service unchecked.
  function isStepActive(stepNum) {
    if (stepNum === 4) return state.services.discord;
    return true;
  }

  function nextStepFrom(stepNum) {
    let n = stepNum + 1;
    while (n <= 6 && !isStepActive(n)) n++;
    return Math.min(n, 6);
  }

  function prevStepFrom(stepNum) {
    let n = stepNum - 1;
    while (n >= 1 && !isStepActive(n)) n--;
    return Math.max(n, 1);
  }

  // ===== Navigation =====

  function showStep(n) {
    state.step = n;
    saveState();

    Object.entries(stepSections).forEach(([num, el]) => {
      const sn = parseInt(num, 10);
      if (sn === n) {
        el.hidden = false;
        el.classList.add('active');
      } else {
        el.hidden = true;
        el.classList.remove('active');
      }
    });

    // Update progress bar
    Object.entries(progressSteps).forEach(([num, el]) => {
      const sn = parseInt(num, 10);
      el.classList.remove('is-current', 'is-complete', 'is-skipped');
      el.removeAttribute('aria-current');
      if (!isStepActive(sn)) {
        el.classList.add('is-skipped');
      } else if (sn < n) {
        el.classList.add('is-complete');
      } else if (sn === n) {
        el.classList.add('is-current');
        el.setAttribute('aria-current', 'step');
      }
    });

    // Focus first input in the active step
    requestAnimationFrame(() => {
      const active = stepSections[String(n)];
      if (!active) return;
      const focusable = active.querySelector(
        'input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])'
      );
      if (focusable) focusable.focus({ preventScroll: false });
    });

    // Re-validate the now-visible step
    validateStep(n);

    // Step 6 generates output on entry
    if (n === 6) generateOutputs();
  }

  function gotoNext(from) {
    const target = nextStepFrom(from);
    showStep(target);
  }

  function gotoBack(target) {
    // From back button: use explicit data-back target, but skip inactive
    let n = parseInt(target, 10);
    while (n >= 1 && !isStepActive(n)) n--;
    showStep(Math.max(n, 1));
  }

  // ===== Validation =====

  function setError(stepNum, msg) {
    const el = document.querySelector(`[data-step-error="${stepNum}"]`);
    if (el) el.textContent = msg || '';
  }

  function setNextEnabled(stepNum, enabled) {
    const btn = stepSections[String(stepNum)].querySelector('.wizard-next');
    if (btn) btn.disabled = !enabled;
  }

  function validateStep(n) {
    switch (n) {
      case 1: {
        const ok = state.mode === 'local' || state.mode === 'nas';
        setNextEnabled(1, ok);
        return ok;
      }
      case 2: {
        const ok = state.services.web || state.services.discord || state.services.autoruns;
        setNextEnabled(2, ok);
        if (!ok) setError(2, 'Pick at least one service.');
        else setError(2, '');
        return ok;
      }
      case 3: {
        // Cash prices come from Google Flights automatically — nothing to configure.
        setNextEnabled(3, true);
        return true;
      }
      case 4: {
        const ok = state.discord.tested_ok;
        setNextEnabled(4, ok);
        return ok;
      }
      case 5: {
        setNextEnabled(5, true);
        return true;
      }
      case 6:
        return true;
    }
    return true;
  }

  // ===== Step 1: mode =====

  $$('input[name="mode"]').forEach((input) => {
    if (state.mode === input.value) input.checked = true;
    input.addEventListener('change', () => {
      state.mode = input.value;
      saveState();
      validateStep(1);
    });
  });

  // ===== Step 2: services =====

  const svcWeb = $('input[name="service-web"]');
  const svcDiscord = $('input[name="service-discord"]');
  const svcAutoruns = $('input[name="service-autoruns"]');

  function syncStep2Inputs() {
    svcWeb.checked = state.services.web;
    svcDiscord.checked = state.services.discord;
    svcAutoruns.checked = state.services.autoruns;
    svcAutoruns.disabled = !state.services.discord;
    const wrap = svcAutoruns.closest('.wizard-check');
    if (wrap) {
      const disabledHelp = wrap.querySelector('[data-disabled-help]');
      const enabledHelp = wrap.querySelector('[data-enabled-help]');
      if (state.services.discord) {
        if (disabledHelp) disabledHelp.hidden = true;
        if (enabledHelp) enabledHelp.hidden = false;
      } else {
        if (disabledHelp) disabledHelp.hidden = false;
        if (enabledHelp) enabledHelp.hidden = true;
      }
    }
  }

  svcWeb.addEventListener('change', () => {
    state.services.web = svcWeb.checked;
    saveState();
    validateStep(2);
  });
  svcDiscord.addEventListener('change', () => {
    state.services.discord = svcDiscord.checked;
    if (!state.services.discord) {
      state.services.autoruns = false;
    }
    saveState();
    syncStep2Inputs();
    syncStep4Visibility();
    validateStep(2);
  });
  svcAutoruns.addEventListener('change', () => {
    state.services.autoruns = svcAutoruns.checked;
    saveState();
    syncStep4Visibility();
    validateStep(2);
  });

  syncStep2Inputs();

  // ===== Step 4: Discord =====

  const discordInputs = {
    token: $('input[name="discord_token"]'),
    guild_id: $('input[name="discord_guild_id"]'),
    notify_channel_id: $('input[name="discord_notify_channel_id"]'),
    run_interval: $('input[name="discord_run_interval"]'),
    demo_mode: $('input[name="discord_demo_mode"]'),
  };
  const intervalOutput = $('output[name="discord_interval_output"]');

  function syncStep4() {
    discordInputs.token.value = state.discord.token || '';
    discordInputs.guild_id.value = state.discord.guild_id || '';
    discordInputs.notify_channel_id.value = state.discord.notify_channel_id || '';
    discordInputs.run_interval.value = state.discord.run_interval_minutes || 60;
    discordInputs.demo_mode.checked = !!state.discord.demo_mode;
    if (intervalOutput) intervalOutput.value = state.discord.run_interval_minutes || 60;

    const status = state.discord.tested_ok
      ? `Connected as ${state.discord.bot_username || 'bot'}`
      : '';
    setStatus('discord', state.discord.tested_ok ? 'ok' : null, status);
  }

  function syncStep4Visibility() {
    $$('[data-show-when="service-autoruns"]').forEach((el) => {
      el.hidden = !state.services.autoruns;
    });
  }

  discordInputs.token.addEventListener('input', () => {
    state.discord.token = discordInputs.token.value.trim();
    state.discord.tested_ok = false;
    state.discord.bot_username = null;
    setStatus('discord', null, '');
    saveState();
    validateStep(4);
  });

  discordInputs.guild_id.addEventListener('input', () => {
    state.discord.guild_id = discordInputs.guild_id.value.trim();
    saveState();
  });

  discordInputs.notify_channel_id.addEventListener('input', () => {
    state.discord.notify_channel_id = discordInputs.notify_channel_id.value.trim();
    saveState();
  });

  discordInputs.run_interval.addEventListener('input', () => {
    const v = parseInt(discordInputs.run_interval.value, 10) || 60;
    state.discord.run_interval_minutes = v;
    if (intervalOutput) intervalOutput.value = v;
    saveState();
  });

  discordInputs.demo_mode.addEventListener('change', () => {
    state.discord.demo_mode = discordInputs.demo_mode.checked;
    saveState();
  });

  // ===== Status pills =====

  function setStatus(key, kind, text) {
    const el = document.querySelector(`[data-status="${key}"]`);
    if (!el) return;
    el.classList.remove('is-ok', 'is-err');
    el.innerHTML = '';
    if (!text) return;
    if (kind === 'ok') {
      el.classList.add('is-ok');
      el.innerHTML = `<span class="pill-status">&#10003;</span><span>${escapeHtml(text)}</span>`;
    } else if (kind === 'err') {
      el.classList.add('is-err');
      el.innerHTML = `<span class="pill-status">&#10007;</span><span>${escapeHtml(text)}</span>`;
    } else {
      el.textContent = text;
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // ===== Test buttons =====

  function withSpinner(btn, fn) {
    const orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span>${orig}`;
    return Promise.resolve()
      .then(fn)
      .finally(() => {
        btn.disabled = false;
        btn.innerHTML = orig;
      });
  }

  $$('.wizard-test-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const which = btn.dataset.test;
      if (which === 'discord') return runDiscordTest(btn);
    });
  });

  function runDiscordTest(btn) {
    setStatus('discord', null, '');
    if (!state.discord.token) {
      setStatus('discord', 'err', 'Enter a bot token first.');
      return;
    }
    return withSpinner(btn, async () => {
      try {
        const res = await fetch('/api/onboard/test/discord', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: state.discord.token }),
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data.ok) {
          state.discord.tested_ok = true;
          state.discord.bot_username = data.bot_username || 'bot';
          saveState();
          setStatus('discord', 'ok', `Connected as ${state.discord.bot_username}`);
          validateStep(4);
        } else {
          state.discord.tested_ok = false;
          state.discord.bot_username = null;
          saveState();
          setStatus('discord', 'err', data.error || `HTTP ${res.status}`);
          validateStep(4);
        }
      } catch (err) {
        state.discord.tested_ok = false;
        saveState();
        setStatus('discord', 'err', (err && err.message) || 'Network error');
        validateStep(4);
      }
    });
  }

  // ===== Step 5: watchlist templates =====

  const stagedListEl = $('[data-staged-list]');
  const stagedEmptyEl = $('[data-staged-empty]');

  function renderStaged() {
    stagedListEl.innerHTML = '';
    state.watchlists.forEach((wl, idx) => {
      const li = document.createElement('li');
      li.className = 'wizard-staged-item';
      if (wl.__status === 'ok') li.classList.add('is-ok');
      if (wl.__status === 'err') li.classList.add('is-err');
      const summary = `${wl.origin}-${wl.destination} ${wl.depart_date} ±${wl.window_days}d ${wl.cabin} pax${wl.passengers} ≥${wl.threshold_cpp}¢ "${wl.label}"`;
      const statusText = wl.__status === 'ok'
        ? '✓ created'
        : wl.__status === 'err'
        ? `✗ ${wl.__error || 'failed'}`
        : '';
      li.innerHTML = `
        <span class="wizard-staged-summary">${escapeHtml(summary)}</span>
        <span class="wizard-staged-status">${escapeHtml(statusText)}</span>
        <button type="button" class="wizard-staged-remove" data-remove-index="${idx}">Remove</button>
      `;
      stagedListEl.appendChild(li);
    });
    stagedEmptyEl.hidden = state.watchlists.length > 0;
  }

  stagedListEl.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-remove-index]');
    if (!btn) return;
    const i = parseInt(btn.dataset.removeIndex, 10);
    state.watchlists.splice(i, 1);
    saveState();
    renderStaged();
  });

  function setActiveTemplate(name) {
    state.step5.activeTemplate = name;
    saveState();
    $$('.wizard-template-btn').forEach((b) => {
      b.classList.toggle('is-active', b.dataset.template === name);
    });
    $$('[data-show-template]').forEach((el) => {
      el.hidden = el.dataset.showTemplate !== name;
    });
  }

  $$('.wizard-template-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const t = btn.dataset.template;
      if (t === 'skip') {
        setActiveTemplate('skip');
      } else {
        setActiveTemplate(t);
      }
    });
  });

  // Holiday template
  $('[data-template-add="holiday"]').addEventListener('click', () => {
    const originInput = $('input[name="holiday_origin"]');
    const origin = (originInput.value || '').trim().toUpperCase();
    if (!/^[A-Z]{3}$/.test(origin)) {
      setError(5, 'Enter a 3-letter airport code (e.g., JFK).');
      return;
    }
    setError(5, '');
    const holidays = [
      { date: '2026-11-26', label: `Thanksgiving from ${origin}` },
      { date: '2026-12-23', label: `Christmas from ${origin}` },
      { date: '2026-12-30', label: `New Year from ${origin}` },
    ];
    holidays.forEach((h) => {
      state.watchlists.push({
        origin,
        destination: '',
        depart_date: h.date,
        window_days: 3,
        cabin: 'economy',
        passengers: 1,
        threshold_cpp: 2.0,
        label: h.label,
        __status: null,
      });
    });
    saveState();
    renderStaged();
  });

  // Custom template
  $('[data-template-add="custom"]').addEventListener('click', () => {
    const get = (n) => ($(`[name="${n}"]`).value || '').trim();
    const origin = get('custom_origin').toUpperCase();
    const destination = get('custom_destination').toUpperCase();
    const depart_date = get('custom_depart_date');
    const window_days = parseInt(get('custom_window_days') || '3', 10);
    const cabin = get('custom_cabin') || 'economy';
    const passengers = parseInt(get('custom_passengers') || '1', 10);
    const threshold_cpp = parseFloat(get('custom_threshold_cpp') || '2.0');
    const label = get('custom_label') || `${origin}-${destination}`;

    if (!/^[A-Z]{3}$/.test(origin)) return setError(5, 'Origin must be a 3-letter IATA code.');
    if (!/^[A-Z]{3}$/.test(destination)) return setError(5, 'Destination must be a 3-letter IATA code.');
    if (!depart_date) return setError(5, 'Depart date required.');
    setError(5, '');

    state.watchlists.push({
      origin,
      destination,
      depart_date,
      window_days,
      cabin,
      passengers,
      threshold_cpp,
      label,
      __status: null,
    });
    // Clear inputs
    ['custom_origin', 'custom_destination', 'custom_depart_date', 'custom_label'].forEach((n) => {
      const el = $(`[name="${n}"]`);
      if (el) el.value = '';
    });
    saveState();
    renderStaged();
  });

  // Seed watchlists when leaving Step 5 forward
  async function seedWatchlists() {
    for (let i = 0; i < state.watchlists.length; i++) {
      const wl = state.watchlists[i];
      if (wl.__status === 'ok') continue;
      try {
        const body = {
          origin: wl.origin,
          destination: wl.destination,
          depart_date: wl.depart_date,
          window_days: wl.window_days,
          cabin: wl.cabin,
          passengers: wl.passengers,
          threshold_cpp: wl.threshold_cpp,
          label: wl.label,
        };
        const res = await fetch('/api/watchlists', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (res.ok) {
          wl.__status = 'ok';
        } else {
          let errText = `HTTP ${res.status}`;
          try {
            const data = await res.json();
            errText = data.error || data.detail || errText;
          } catch (_) {
            /* ignore */
          }
          wl.__status = 'err';
          wl.__error = errText;
        }
      } catch (err) {
        wl.__status = 'err';
        wl.__error = (err && err.message) || 'network error';
      }
      saveState();
      renderStaged();
    }
  }

  // ===== Step 6: generate / outputs =====

  async function generateOutputs() {
    const envPre = document.querySelector('[data-output="env-output"] code');
    const composePre = document.querySelector('[data-output="compose-output"] code');
    if (envPre) envPre.textContent = 'Generating...';
    if (composePre) composePre.textContent = 'Generating...';

    // Toggle compose tab based on mode
    const composeTab = document.querySelector('.wizard-tab[data-tab="compose"]');
    const composePanel = document.querySelector('[data-tab-panel="compose"]');
    if (state.mode !== 'nas') {
      if (composeTab) composeTab.hidden = true;
      if (composePanel) composePanel.hidden = true;
      // Force env tab active
      activateTab('env');
    } else {
      if (composeTab) composeTab.hidden = false;
    }

    const services = [];
    if (state.services.web) services.push('web');
    if (state.services.discord) services.push('discord');
    if (state.services.autoruns) services.push('autoruns');

    const payload = {
      mode: state.mode,
      services,
      discord: {
        enabled: !!state.services.discord,
        token: state.discord.token || '',
        guild_id: state.discord.guild_id || '',
        notify_channel_id: state.discord.notify_channel_id || null,
        run_interval_minutes: state.discord.run_interval_minutes || 60,
        demo_mode: !!state.discord.demo_mode,
      },
    };

    try {
      const res = await fetch('/api/onboard/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || data.detail || `HTTP ${res.status}`);
      if (envPre) envPre.textContent = data.env || '';
      if (composePre) composePre.textContent = data.compose || '';
      setError(6, '');
    } catch (err) {
      if (envPre) envPre.textContent = '';
      if (composePre) composePre.textContent = '';
      setError(6, `Could not generate config: ${(err && err.message) || 'unknown error'}`);
    }
  }

  function activateTab(name) {
    $$('.wizard-tab').forEach((t) => {
      const on = t.dataset.tab === name;
      t.classList.toggle('is-active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    $$('.wizard-tab-panel').forEach((p) => {
      const on = p.dataset.tabPanel === name;
      p.classList.toggle('is-active', on);
      p.hidden = !on;
    });
  }

  $$('.wizard-tab').forEach((tab) => {
    tab.addEventListener('click', () => activateTab(tab.dataset.tab));
  });

  // Copy / download
  $$('.wizard-copy').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const target = document.querySelector(`[data-output="${btn.dataset.copyTarget}"] code`);
      if (!target) return;
      try {
        await navigator.clipboard.writeText(target.textContent || '');
        btn.classList.add('is-copied');
        const orig = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => {
          btn.classList.remove('is-copied');
          btn.textContent = orig;
        }, 1500);
      } catch (_) {
        // Fallback: select
        const range = document.createRange();
        range.selectNodeContents(target);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
    });
  });

  $$('.wizard-download').forEach((btn) => {
    btn.addEventListener('click', () => {
      const target = document.querySelector(`[data-output="${btn.dataset.downloadTarget}"] code`);
      if (!target) return;
      const blob = new Blob([target.textContent || ''], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = btn.dataset.filename || 'output.txt';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    });
  });

  // Done actions
  $('[data-action="finish"]').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    await withSpinner(btn, async () => {
      try {
        await fetch('/api/onboard/complete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        });
      } catch (_) {
        // Best-effort; still proceed
      }
      try {
        sessionStorage.removeItem(STORAGE_KEY);
      } catch (_) {
        /* ignore */
      }
      window.location.href = '/';
    });
  });

  $('[data-action="rerun"]').addEventListener('click', () => {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch (_) {
      /* ignore */
    }
    window.location.href = '/onboard';
  });

  // ===== Wire next/back =====

  $$('.wizard-next').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const from = parseInt(btn.dataset.next, 10) - 1; // current step
      if (!validateStep(from)) return;
      // Step 5 → seed watchlists before advancing
      if (from === 5 && state.watchlists.length > 0) {
        await withSpinner(btn, async () => {
          await seedWatchlists();
        });
      }
      gotoNext(from);
    });
  });

  $$('.wizard-back').forEach((btn) => {
    btn.addEventListener('click', () => gotoBack(btn.dataset.back));
  });

  // ===== On-load init: hydrate UI from state =====

  syncStep4();
  syncStep4Visibility();
  if (state.step5.activeTemplate) setActiveTemplate(state.step5.activeTemplate);
  renderStaged();

  // If we previously persisted past Step 1, also check status from the server
  // to decide if the user should even be here. (Non-blocking.)
  (async function checkStatus() {
    try {
      const res = await fetch('/api/onboard/status');
      if (!res.ok) return;
      const data = await res.json();
      // If configured and the user didn't ask to re-run, nothing to do here —
      // the parent FastAPI route is responsible for redirecting. We just store
      // the info for any future logic.
      window.__autopointsOnboardStatus = data;
    } catch (_) {
      /* ignore */
    }
  })();

  // Validate current step and render
  showStep(state.step || 1);
})();
