<script>
  let {
    /** @type {string | null} */
    error = null,
    /** @type {Array<{ filename: string, message: string }>} */
    warnings = [],
    /** @type {() => void} */
    ondismiss = () => {},
  } = $props();
</script>

<div class="banner" role="status" aria-live="polite">
  <div class="banner-content">
    {#if error !== null}
      <div class="banner-body is-error">
        <span class="banner-title">Error</span>
        <p class="banner-text">{error}</p>
      </div>
    {/if}

    {#if warnings.length > 0}
      <div class="banner-body is-warning">
        <span class="banner-title">
          {warnings.length} file{warnings.length === 1 ? '' : 's'} not aligned
        </span>
        <ul class="banner-list">
          {#each warnings as item, index (`${item.filename}-${index}`)}
            <li>
              <span class="banner-file">{item.filename}</span>
              <span class="banner-text">{item.message}</span>
            </li>
          {/each}
        </ul>
      </div>
    {/if}
  </div>

  <!-- the arrow form keeps svelte-check's JS-mode prop typing happy -->
  <button type="button" class="banner-dismiss" onclick={() => ondismiss()}>Dismiss</button>
</div>
