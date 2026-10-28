/**
 * Normalises the two response shapes (/api/align and /api/pagexml) into one
 * document list the results panel can render without branching.
 */

const EMPTY_DOC = {
  label: '',
  ref: '',
  results: [],
  summary: null,
  confusions: [],
  files: null,
  xml_path: null,
};

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

/**
 * @param {any} value
 * @returns {import('./types.js').AlignedDocument}
 */
export function toDocument(value) {
  if (!value || typeof value !== 'object') return { ...EMPTY_DOC };
  return {
    label: typeof value.label === 'string' ? value.label : '',
    ref: typeof value.ref === 'string' ? value.ref : '',
    results: asArray(value.results),
    summary: value.summary && typeof value.summary === 'object' ? value.summary : null,
    confusions: asArray(value.confusions),
    files:
      value.files && typeof value.files === 'object'
        ? {
            csv: typeof value.files.csv === 'string' ? value.files.csv : '',
            txt: typeof value.files.txt === 'string' ? value.files.txt : '',
            confusions_csv:
              typeof value.files.confusions_csv === 'string' ? value.files.confusions_csv : '',
          }
        : null,
    xml_path: typeof value.xml_path === 'string' ? value.xml_path : null,
  };
}

/**
 * @param {string} ref
 * @param {any} response
 * @returns {any[]}
 */
export function docsFromAlign(ref, response) {
  if (!response || typeof response !== 'object') return [];
  return [
    toDocument({
      label: ref,
      ref,
      results: response.results,
      summary: response.summary,
      confusions: response.confusions,
      files: response.files,
    }),
  ];
}

/**
 * @param {any} response
 * @returns {{ documents: any[], errors: Array<{ filename: string, message: string }> }}
 */
export function parsePagexml(response) {
  const documents = asArray(response?.documents).map((entry) =>
    toDocument({
      label: typeof entry?.filename === 'string' ? entry.filename : 'document.xml',
      ref: typeof entry?.ref === 'string' ? entry.ref : '',
      results: entry?.results,
      summary: entry?.summary,
      confusions: entry?.confusions,
      files: entry?.files,
      xml_path: entry?.xml_path,
    }),
  );

  const errors = asArray(response?.errors)
    .filter((entry) => entry && typeof entry === 'object')
    .map((entry) => ({
      filename: typeof entry.filename === 'string' ? entry.filename : 'unknown file',
      message: typeof entry.message === 'string' ? entry.message : 'Alignment failed.',
    }));

  return { documents, errors };
}

/**
 * @param {{ csv?: string, txt?: string, confusions_csv?: string } | null} files
 */
export function hasExports(files) {
  return Boolean(files && (files.csv || files.txt || files.confusions_csv));
}
