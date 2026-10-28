<script>
  import { formatScore, formatPercent } from './format.js';

  let {
    /** @type {import('./types.js').Summary | null} */
    summary = null,
    /** @type {string} */
    source = '',
  } = $props();
</script>

{#if summary !== null}
  <div class="summary">
    {#if source !== ''}
      <p class="summary-source">{source}</p>
    {/if}
    <dl class="tiles">
      <div class="tile">
        <dt>Lines</dt>
        <dd>{summary.lines ?? 0}</dd>
      </div>
      <div class="tile">
        <dt>Average score</dt>
        <dd>{formatScore(summary.average_score)}</dd>
      </div>
      <div class="tile">
        <dt>Threshold</dt>
        <dd>{summary.threshold ?? 70}</dd>
      </div>
      <div class="tile">
        <dt>Low confidence</dt>
        <dd>
          {summary.low_count ?? 0}
          <span class="tile-sub">{formatPercent(summary.low_pct)}</span>
        </dd>
      </div>
    </dl>
  </div>
{/if}
