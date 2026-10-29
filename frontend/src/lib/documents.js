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
  page: null,
};

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function positiveInt(value) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

/**
 * The page image a PAGE-XML document was aligned with, and the polygon each result
 * line occupies on it. Null when no image was supplied.
 *
 * @param {any} value
 * @returns {import('./types.js').PageImage | null}
 */
function toPage(value) {
  const url = typeof value?.image_url === 'string' ? value.image_url : null;
  const filename = typeof value?.image_filename === 'string' ? value.image_filename : null;
  const error = typeof value?.image_error === 'string' ? value.image_error : null;
  const width = positiveInt(value?.image_width);
  const height = positiveInt(value?.image_height);
  const crops = asArray(value?.crops)
    .filter((crop) => crop && typeof crop === 'object' && typeof crop.points === 'string')
    .map((crop) => ({ line_no: Number(crop.line_no), points: crop.points }));

  // An image that failed to store is still reported, so the row can say why it is missing.
  if (!url && !error && !filename) return null;
  return { url, filename, error, width, height, crops };
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
    page: toPage(value),
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
      image_url: entry?.image_url,
      image_filename: entry?.image_filename,
      image_width: entry?.image_width,
      image_height: entry?.image_height,
      image_error: entry?.image_error,
      crops: entry?.crops,
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
 * What to draw for one result line: its polygon plus the image it is cut from. Null when the
 * line has no polygon, or when there is no image with usable dimensions to cut.
 *
 * @param {import('./types.js').AlignedDocument | null | undefined} doc
 * @param {number} lineNo
 * @returns {import('./types.js').LineCropView | null}
 */
export function cropFor(doc, lineNo) {
  const page = doc?.page;
  if (!page?.url || !page.width || !page.height) return null;
  const crop = asArray(page.crops).find((entry) => entry.line_no === Number(lineNo));
  if (!crop) return null;
  return {
    url: page.url,
    width: page.width,
    height: page.height,
    points: crop.points,
  };
}

/**
 * @param {{ csv?: string, txt?: string, confusions_csv?: string } | null} files
 */
export function hasExports(files) {
  return Boolean(files && (files.csv || files.txt || files.confusions_csv));
}
