const API_BASE = '/api';

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, options);
  } catch {
    throw new ApiError(
      `Cannot reach the alignment server at ${API_BASE}. Is it running on port 8000?`,
      0,
    );
  }

  const body = await response.text();
  let payload = null;
  if (body !== '') {
    try {
      payload = JSON.parse(body);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const detail = payload && (payload.detail ?? payload.message);
    throw new ApiError(
      typeof detail === 'string' && detail !== ''
        ? detail
        : `Request to ${path} failed with status ${response.status}.`,
      response.status,
    );
  }

  if (payload === null) {
    throw new ApiError(`Server returned an unreadable response for ${path}.`, response.status);
  }
  return payload;
}

function jsonRequest(method, path, body) {
  return request(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export const api = {
  health: () => request('/health'),

  refs: () => request('/refs'),

  align: ({ ref, ocrText, threshold }) =>
    jsonRequest('POST', '/align', { ref, ocr_text: ocrText, threshold }),

  pagexml: ({ ref, threshold, files, images = [] }) => {
    const form = new FormData();
    form.append('ref', ref);
    form.append('threshold', String(threshold));
    for (const file of files) form.append('files', file, file.name);
    for (const image of images) form.append('images', image, image.name);
    return request('/pagexml', { method: 'POST', body: form });
  },

  export: ({ ref, results, confusions }) =>
    jsonRequest('POST', '/export', { ref, results, confusions }),
};

export function downloadFile(filename, content, mime = 'text/plain;charset=utf-8') {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
