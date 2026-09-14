// Uploading bytes to Mantle.
//
// ⛔ THERE IS ONE UPLOAD PATH, AND IT IS A SINGLE PROXIED PUT. Mantle envelope-encrypts on the
// byte path (`workspace_service.initiate_upload`), so the object store never receives plaintext
// and cannot issue a presigned URL — there is no chunked or direct-to-store mode to fall back to
// while content is encrypted at rest.
//
// ⚠ A CHUNKED PATH LIVED HERE AND COULD NEVER RUN. It fetched a per-part presigned URL from an
// artifact sub-resource no service has ever served, and was reached only when `upload-initiate`
// returned a chunked mode, which it never does.
// Its tests passed throughout by mocking the call — they pinned the shape its author intended,
// not the one the server has. Removed 2026-09-13 with the endpoint measured absent (404).

// Upload utility functions for file handling

import { updateUploadStatus } from '../api/workspaces';

/**
 * PUT a file to Mantle, reporting progress to the caller and to the server.
 */
export async function uploadWithProgress(
  workspaceId: string,
  uploadId: string,
  url: string,
  file: File,
  onProgress?: (progress: number) => void
): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    xhr.setRequestHeader("Cache-Control", "private, max-age=31536000, immutable");

    // ⛔ THE BEARER IS REQUIRED NOW, AND IT WAS NOT WHEN THIS WAS WRITTEN. The URL used to be a
    // presigned S3 link that carried its own authorization; it is a Mantle route today, and Mantle
    // answers 401 without a token. This is raw XHR — it does not pass through the axios instance,
    // so the request interceptor that attaches the header never sees it. Measured 2026-09-13: the
    // proxied PUT returned 401 until this was added.
    const token = localStorage.getItem("access_token");
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    
    // Send progress updates to backend
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const progress = e.loaded / e.total;
        
        // Notify callback for local UI updates
        onProgress?.(progress);
        
        // Also send to backend (fire and forget)
        updateUploadStatus(workspaceId, uploadId, {
          status: "uploading",
          progress: progress,
        }).catch(() => {/* ignore progress update failures */});
      }
    };
    
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`PUT ${xhr.status}`)));
    xhr.onerror = () => reject(new Error("PUT network error"));
    xhr.send(file);
  });
}
