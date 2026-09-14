// api/types/upload.ts

export interface UploadInitiateRequest {
  filename: string;
  content_type: string;
  size: number;
  order_key?: string; // Fractional index key for artifact ordering
  context?: Record<string, unknown>;
}

export interface UploadInitiateResponse {
  upload_id: string; // Artifact ID

  /**
   * How to send the bytes. `proxied` is the only value this platform returns.
   *
   * ⛔ IT USED TO SAY `"inline" | "put" | "multipart"`, AND THE SERVER RETURNS NONE OF THOSE.
   * `workspace_service.initiate_upload` sets `"proxied"` unconditionally, so every upload fell
   * through `Browser.tsx`'s mode branch to `throw new Error("Unexpected upload mode…")` — file
   * upload was broken for every file, presented to the user as "Please contact support".
   * Measured against a live node 2026-09-13.
   *
   * ⚠ THERE IS NO PRESIGNED-URL MODE WHILE CONTENT IS ENCRYPTED AT REST, and that is a property
   * of the design rather than a gap: Mantle envelope-encrypts on the byte path, so the object
   * store never receives plaintext and cannot hand out a direct URL. `content_service` still
   * carries `"put"` and `"multipart"` for an unencrypted S3 path this route does not use — which
   * is where the old values came from.
   */
  mode: "proxied";

  /**
   * Where to send them — **relative to Mantle**, e.g. `/artifacts/{id}/content`.
   *
   * ⚠ RESOLVE IT AGAINST THE MANTLE BASE BEFORE USE. Given to `XMLHttpRequest` as-is it resolves
   * against the page's own origin, where no proxy rule matches it and the SPA fallback answers
   * `index.html` at 200 — an upload that reports success and stores nothing.
   */
  url: string;

  method: string; // The verb to use for `url` — "PUT".
  key: string; // Content key in the store (internal use).
  artifact: Record<string, unknown>; // The created artifact object.
  // Use GET /artifacts/{artifact_id}/content-url to obtain a signed URL for the file.
}

export interface UploadStatusUpdateRequest {
  status: "uploading" | "complete" | "failed";
  progress?: number;
  parts?: Array<{ part_number: number; etag: string }>;
  context_patch?: Record<string, unknown>;
}
