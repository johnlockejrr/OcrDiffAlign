/**
 * Shared JSDoc type definitions for the Svelte components.
 * @module
 */

/**
 * @typedef {Object} AlignResult
 * @property {number} line_no
 * @property {string} ocr
 * @property {string} normalized
 * @property {string} match
 * @property {number} score
 * @property {number} ref_index
 * @property {string} final_match
 * @property {string} diff_html
 */

/**
 * @typedef {Object} Summary
 * @property {number} [lines]
 * @property {number} [average_score]
 * @property {number} [threshold]
 * @property {number} [low_count]
 * @property {number} [low_pct]
 */

/**
 * @typedef {Object} Confusion
 * @property {string} ocr_char
 * @property {string} ref_char
 * @property {number} count
 */

/**
 * @typedef {Object} ExportFiles
 * @property {string} csv
 * @property {string} txt
 * @property {string} confusions_csv
 */

/**
 * @typedef {Object} LineCrop
 * @property {number} line_no
 * @property {string} points
 */

/**
 * One renderable crop: a line's polygon and the page image it is cut from.
 *
 * @typedef {Object} LineCropView
 * @property {string} url
 * @property {number} width
 * @property {number} height
 * @property {string} points
 */

/**
 * The page image a PAGE-XML document was aligned with. `url` is null when the image
 * was not supplied or could not be stored, in which case `error` explains why.
 *
 * @typedef {Object} PageImage
 * @property {string | null} url
 * @property {string | null} filename
 * @property {string | null} error
 * @property {number | null} width
 * @property {number | null} height
 * @property {LineCrop[]} crops
 */

/**
 * @typedef {Object} AlignedDocument
 * @property {string} label
 * @property {string} ref
 * @property {AlignResult[]} results
 * @property {Summary | null} summary
 * @property {Confusion[]} confusions
 * @property {ExportFiles | null} files
 * @property {string | null} xml_path
 * @property {PageImage | null} page
 */

/**
 * @typedef {Object} RefFile
 * @property {string} name
 * @property {number} size_bytes
 */

export {};
