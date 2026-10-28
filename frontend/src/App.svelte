<script>
  import { onMount } from 'svelte';
  import { api } from './lib/api.js';
  import Controls from './lib/Controls.svelte';
  import ResultsPanel from './lib/ResultsPanel.svelte';
  import ErrorBanner from './lib/ErrorBanner.svelte';
  import { docsFromAlign, parsePagexml } from './lib/documents.js';

  let mode = $state('text');
  let refs = $state([]);
  let ref = $state('');
  let ocrText = $state('');
  let threshold = $state(70);
  let xmlFiles = $state([]);

  let loading = $state(false);
  let error = $state(null);
  let warnings = $state([]);
  let documents = $state([]);
  let selected = $state(0);
  let dirty = $state(false);
  let serverOnline = $state(null);

  async function bootstrap() {
    try {
      await api.health();
      serverOnline = true;
      const payload = await api.refs();
      refs = Array.isArray(payload.refs) ? payload.refs : [];
      ref = refs[0]?.name ?? '';
    } catch (err) {
      serverOnline = false;
      error = err.message;
    }
  }

  onMount(() => {
    void bootstrap();
  });

  const canRun = $derived(
    !loading &&
      serverOnline !== false &&
      ref !== '' &&
      (mode === 'text' ? ocrText.trim() !== '' : xmlFiles.length > 0),
  );

  const currentDoc = $derived(documents[Math.min(selected, Math.max(documents.length - 1, 0))] ?? null);

  async function run() {
    loading = true;
    error = null;
    warnings = [];
    try {
      if (mode === 'text') {
        documents = docsFromAlign(ref, await api.align({ ref, ocrText, threshold }));
      } else {
        const parsed = parsePagexml(await api.pagexml({ ref, threshold, files: xmlFiles }));
        documents = parsed.documents;
        warnings = parsed.errors;
        if (parsed.documents.length === 0 && parsed.errors.length === 0) {
          error = 'The server returned no documents for the selected PAGE-XML files.';
        }
      }
      selected = 0;
      dirty = false;
    } catch (err) {
      error = err.message;
    } finally {
      loading = false;
    }
  }

  /** @param {any} row @param {string} value */
  function onEdit(row, value) {
    row.final_match = value;
    dirty = true;
  }

  async function exportCurrent() {
    if (!currentDoc) return;
    loading = true;
    error = null;
    try {
      const exported = await api.export({
        ref: currentDoc.ref || ref,
        results: currentDoc.results,
        confusions: currentDoc.confusions,
      });
      const files = {
        csv: typeof exported.csv === 'string' ? exported.csv : '',
        txt: typeof exported.txt === 'string' ? exported.txt : '',
        confusions_csv:
          typeof exported.confusions_csv === 'string' ? exported.confusions_csv : '',
      };
      documents = documents.map((doc, index) =>
        index === Math.min(selected, documents.length - 1) ? { ...doc, files } : doc,
      );
      dirty = false;
    } catch (err) {
      error = err.message;
    } finally {
      loading = false;
    }
  }

  /** @param {string} message */
  function notify(message) {
    error = message;
  }
</script>

<div class="app">
  <header class="masthead">
    <div>
      <h1>OCR Diff Align</h1>
      <p class="subtitle">Hebrew OCR alignment against a reference text</p>
    </div>
    <p
      class="status"
      class:online={serverOnline === true}
      class:offline={serverOnline === false}
    >
      {serverOnline === null ? 'Checking server' : serverOnline ? 'Server reachable' : 'Server unreachable'}
    </p>
  </header>

  {#if error !== null || warnings.length > 0}
    <ErrorBanner
      {error}
      {warnings}
      ondismiss={() => {
        error = null;
        warnings = [];
      }}
    />
  {/if}

  <Controls
    bind:mode
    {refs}
    bind:ref
    bind:text={ocrText}
    bind:threshold
    bind:xmlFiles
    {loading}
    {canRun}
    canExport={currentDoc !== null}
    {dirty}
    onrun={run}
    onexport={exportCurrent}
    {notify}
  />

  {#if currentDoc !== null}
    <ResultsPanel
      {documents}
      bind:selected
      {onEdit}
      ongenerate={exportCurrent}
      {loading}
    />
  {:else}
    <section class="empty" aria-live="polite">
      <p>No alignment yet. Pick a reference text, provide OCR input, then run an alignment.</p>
    </section>
  {/if}
</div>
