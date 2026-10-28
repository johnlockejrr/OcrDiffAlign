<script>
  import SummaryBar from './SummaryBar.svelte';
  import DownloadGroup from './DownloadGroup.svelte';
  import ResultRow from './ResultRow.svelte';

  const PAGE_SIZE = 10;

  let {
    /** @type {import('./types.js').AlignedDocument[]} */
    documents,
    /** @type {number} */
    selected = $bindable(0),
    /** @type {(row: import('./types.js').AlignResult, value: string) => void} */
    onEdit = () => {},
    /** @type {() => void | Promise<void>} */
    ongenerate = () => {},
    /** @type {boolean} */
    loading = false,
  } = $props();

  let page = $state(0);

  const doc = $derived(documents[Math.min(selected, Math.max(documents.length - 1, 0))] ?? null);
  const rows = $derived(doc?.results ?? []);
  const pageCount = $derived(Math.max(1, Math.ceil(rows.length / PAGE_SIZE)));
  const safePage = $derived(Math.min(page, pageCount - 1));
  const visible = $derived(rows.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE));
  const threshold = $derived(doc?.summary?.threshold ?? 70);

  /** @param {number} index */
  function selectDoc(index) {
    selected = index;
    page = 0;
  }
</script>

<section class="results" aria-label="Alignment results">
  {#if documents.length > 1}
    <div class="doc-tabs">
      {#each documents as item, index (`${item.label}-${index}`)}
        <button
          type="button"
          class="doc-tab"
          class:active={index === Math.min(selected, documents.length - 1)}
          onclick={() => selectDoc(index)}
        >
          {item.label || `Document ${index + 1}`}
        </button>
      {/each}
    </div>
  {/if}

  {#if doc !== null}
    <SummaryBar summary={doc.summary} source={doc.xml_path ?? doc.ref ?? doc.label} />
    <DownloadGroup files={doc.files} {loading} {ongenerate} />

    {#if rows.length > 0}
      <nav class="pager" aria-label="Result pages">
        <button
          type="button"
          onclick={() => (page = Math.max(0, safePage - 1))}
          disabled={safePage === 0}
        >
          Previous
        </button>
        <span class="pager-text">Page {safePage + 1} of {pageCount}</span>
        <button
          type="button"
          onclick={() => (page = Math.min(pageCount - 1, safePage + 1))}
          disabled={safePage >= pageCount - 1}
        >
          Next
        </button>
      </nav>

      <ol class="rows">
        {#each visible as row, index (`${row.line_no}-${index}`)}
          <ResultRow {row} {threshold} {onEdit} />
        {/each}
      </ol>
    {:else}
      <p class="empty">This document produced no aligned lines.</p>
    {/if}
  {/if}
</section>
