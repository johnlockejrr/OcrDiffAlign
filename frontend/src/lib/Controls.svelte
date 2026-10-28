<script>
  import { formatBytes } from './format.js';

  let {
    /** @type {'text' | 'pagexml'} */
    mode = $bindable('text'),
    /** @type {Array<{ name: string, size_bytes: number }>} */
    refs = [],
    /** @type {string} */
    ref = $bindable(''),
    /** @type {string} */
    text = $bindable(''),
    /** @type {number} */
    threshold = $bindable(70),
    /** @type {File[]} */
    xmlFiles = $bindable([]),
    /** @type {boolean} */
    loading = false,
    /** @type {boolean} */
    canRun = false,
    /** @type {boolean} */
    canExport = false,
    /** @type {boolean} */
    dirty = false,
    /** @type {() => void | Promise<void>} */
    onrun = () => {},
    /** @type {() => void | Promise<void>} */
    onexport = () => {},
    /** @type {(message: string) => void} */
    notify = () => {},
  } = $props();

  /** @param {number | string} raw */
  function clampThreshold(raw) {
    const value = Math.round(Number(raw));
    if (!Number.isFinite(value)) return 0;
    return Math.min(100, Math.max(0, value));
  }

  /** @param {Event} event */
  async function readTextFile(event) {
    const file = /** @type {HTMLInputElement} */ (event.target).files?.[0];
    if (!file) return;
    try {
      text = await file.text();
    } catch {
      notify(`Could not read ${file.name}.`);
    }
  }

  /** @param {Event} event */
  function pickXmlFiles(event) {
    xmlFiles = [.../** @type {HTMLInputElement} */ (event.target).files];
  }
</script>

<section class="controls" aria-label="Alignment settings">
  <div class="segmented">
    <button
      type="button"
      class="segment"
      class:active={mode === 'text'}
      aria-pressed={mode === 'text'}
      onclick={() => (mode = 'text')}
    >
      Plain OCR text
    </button>
    <button
      type="button"
      class="segment"
      class:active={mode === 'pagexml'}
      aria-pressed={mode === 'pagexml'}
      onclick={() => (mode = 'pagexml')}
    >
      PAGE-XML
    </button>
  </div>

  <div class="row-grid">
    <label class="field">
      <span class="field-label">Reference text</span>
      <select value={ref} onchange={(event) => (ref = event.currentTarget.value)}>
        {#if refs.length === 0}
          <option value="">No reference files available</option>
        {/if}
        {#each refs as item (item.name)}
          <option value={item.name}>{item.name}</option>
        {/each}
      </select>
    </label>

    <div class="field">
      <span class="field-label" id="threshold-label">Low-score threshold</span>
      <div class="threshold">
        <input
          type="range"
          min="0"
          max="100"
          step="1"
          value={threshold}
          aria-labelledby="threshold-label"
          oninput={(event) => (threshold = clampThreshold(event.currentTarget.value))}
        />
        <input
          type="number"
          min="0"
          max="100"
          step="1"
          value={threshold}
          aria-labelledby="threshold-label"
          oninput={(event) => (threshold = clampThreshold(event.currentTarget.value))}
        />
      </div>
    </div>
  </div>

  {#if mode === 'text'}
    <label class="field">
      <span class="field-label">OCR text</span>
      <textarea
        class="hebrew"
        rows="8"
        placeholder="Paste line-separated OCR output"
        value={text}
        oninput={(event) => (text = event.currentTarget.value)}
      ></textarea>
    </label>

    <label class="field">
      <span class="field-label">Or load a .txt file</span>
      <input type="file" accept=".txt,text/plain" onchange={readTextFile} />
    </label>
  {:else}
    <label class="field">
      <span class="field-label">PAGE-XML files</span>
      <input
        type="file"
        accept=".xml,text/xml,application/xml"
        multiple
        onchange={pickXmlFiles}
      />
    </label>

    {#if xmlFiles.length > 0}
      <ul class="file-list" aria-label="Selected PAGE-XML files">
        {#each xmlFiles as file, index (`${file.name}-${index}`)}
          <li>
            <span class="file-name">{file.name}</span>
            <span class="file-size">{formatBytes(file.size)}</span>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}

  <div class="actions">
    <button type="button" class="primary" onclick={onrun} disabled={!canRun}>
      {#if loading}
        <span class="spinner" aria-hidden="true"></span>
        <span>Working</span>
      {:else}
        <span>Run alignment</span>
      {/if}
    </button>
    <button type="button" onclick={onexport} disabled={!canExport || loading}>
      Save / Export
    </button>
    {#if dirty}
      <span class="dirty-mark">Unsaved changes</span>
    {/if}
  </div>
</section>
