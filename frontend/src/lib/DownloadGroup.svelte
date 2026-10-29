<script>
  import { downloadFile } from './api.js';

  let {
    /** @type {import('./types.js').ExportFiles | null} */
    files = null,
    /** @type {boolean} */
    busy = false,
    /** @type {() => void | Promise<void>} */
    ongenerate = () => {},
  } = $props();

  /** @param {string} filename @param {string} content @param {string} mime */
  function save(filename, content, mime) {
    if (content === '') return;
    downloadFile(filename, content, mime);
  }
</script>

<div class="downloads">
  {#if files !== null && (files.csv !== '' || files.txt !== '' || files.confusions_csv !== '')}
    <button
      type="button"
      onclick={() => save('alignment.csv', files?.csv ?? '', 'text/csv;charset=utf-8')}
      disabled={files?.csv === ''}
    >
      Alignment CSV
    </button>
    <button
      type="button"
      onclick={() => save('matched_text.txt', files?.txt ?? '', 'text/plain;charset=utf-8')}
      disabled={files?.txt === ''}
    >
      Matched text
    </button>
    <button
      type="button"
      onclick={() =>
        save('confusions.csv', files?.confusions_csv ?? '', 'text/csv;charset=utf-8')}
      disabled={files?.confusions_csv === ''}
    >
      Confusion log
    </button>
  {:else}
    <!-- the arrow form keeps svelte-check's JS-mode prop typing happy -->
    <button type="button" onclick={() => ongenerate()} disabled={busy}>
      {busy ? 'Generating' : 'Generate exports'}
    </button>
    <p class="downloads-hint">
      This document has no exported files yet. Generating them writes the aligned output to the
      server output directory.
    </p>
  {/if}
</div>
