// Tests for upload utility functions
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { uploadWithProgress } from '../upload';
import * as workspacesApi from '../../api/workspaces';

// Mock the API
vi.mock('../../api/workspaces', () => ({
  updateUploadStatus: vi.fn(),
}));

interface MockXHR {
  open: ReturnType<typeof vi.fn>;
  send: ReturnType<typeof vi.fn>;
  setRequestHeader: ReturnType<typeof vi.fn>;
  getResponseHeader: ReturnType<typeof vi.fn>;
  upload: {
    onprogress?: (e: ProgressEvent) => void;
  };
  status: number;
  onload: (() => void) | null;
  onerror: (() => void) | null;
}

describe('uploadWithProgress', () => {
  let mockXHR: MockXHR;
  
  beforeEach(() => {
    vi.useFakeTimers();
    mockXHR = {
      open: vi.fn(),
      send: vi.fn(),
      setRequestHeader: vi.fn(),
      getResponseHeader: vi.fn(),
      upload: {},
      status: 0,
      onload: null,
      onerror: null,
    };
    
    globalThis.XMLHttpRequest = vi.fn(function() {
      return mockXHR;
    }) as unknown as typeof XMLHttpRequest;
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('should upload file with progress tracking', async () => {
    const file = new File(['test content'], 'test.txt', { type: 'text/plain' });
    const workspaceId = 'workspace-1';
    const uploadId = 'upload-1';
    const url = 'https://example.com/upload';
    const onProgress = vi.fn();
    
    vi.mocked(workspacesApi.updateUploadStatus).mockResolvedValue({
      id: uploadId,
      context: { upload: { status: 'uploading', progress: 0.5 } }
    } as never);
    mockXHR.status = 200;
    
    const promise = uploadWithProgress(workspaceId, uploadId, url, file, onProgress);
    
    // Simulate progress
    mockXHR.upload.onprogress?.(new ProgressEvent('progress', {
      lengthComputable: true,
      loaded: 50,
      total: 100,
    }));
    
    // Flush any scheduled progress/status work deterministically
    vi.advanceTimersByTime(20);
    await vi.runOnlyPendingTimersAsync();
    
    // Complete upload
    if (mockXHR.onload) mockXHR.onload();
    await promise;
    
    expect(onProgress).toHaveBeenCalledWith(0.5);
    expect(workspacesApi.updateUploadStatus).toHaveBeenCalledWith(
      workspaceId,
      uploadId,
      { status: 'uploading', progress: 0.5 }
    );
    expect(mockXHR.setRequestHeader).toHaveBeenCalledWith('Content-Type', 'text/plain');
    expect(mockXHR.setRequestHeader).toHaveBeenCalledWith('Cache-Control', 'private, max-age=31536000, immutable');
  });

  it('should handle upload without progress callback', async () => {
    const file = new File(['test'], 'test.txt');
    const workspaceId = 'workspace-1';
    const uploadId = 'upload-1';
    const url = 'https://example.com/upload';
    
    vi.mocked(workspacesApi.updateUploadStatus).mockResolvedValue({
      id: uploadId,
      context: { upload: { status: 'uploading', progress: 1.0 } }
    } as never);
    mockXHR.status = 201;
    
    const promise = uploadWithProgress(workspaceId, uploadId, url, file);
    
    // Simulate progress
    mockXHR.upload.onprogress?.(new ProgressEvent('progress', {
      lengthComputable: true,
      loaded: 100,
      total: 100,
    }));
    
    // Flush any scheduled progress/status work deterministically
    vi.advanceTimersByTime(20);
    await vi.runOnlyPendingTimersAsync();
    
    if (mockXHR.onload) mockXHR.onload();
    await promise;
    
    expect(workspacesApi.updateUploadStatus).toHaveBeenCalled();
  });

  it('should reject on upload failure', async () => {
    const file = new File(['test'], 'test.txt');
    const workspaceId = 'workspace-1';
    const uploadId = 'upload-1';
    const url = 'https://example.com/upload';
    
    mockXHR.status = 403;
    
    const promise = uploadWithProgress(workspaceId, uploadId, url, file);
    
    if (mockXHR.onload) mockXHR.onload();
    
    await expect(promise).rejects.toThrow('PUT 403');
  });

  // ── the bearer ────────────────────────────────────────────────────────────────────────────
  //
  // ⛔ WITHOUT THIS HEADER EVERY PROXIED UPLOAD IS REJECTED, AND NOTHING ELSE HERE NOTICES. The
  // URL used to be a presigned S3 link carrying its own authorization; it is a Mantle route now,
  // and Mantle answers 401 without a token. This is raw XHR, so the axios request interceptor that
  // attaches the header never sees it — measured 2026-09-13, the proxied PUT returned 401 until
  // `upload.ts` set it explicitly.
  //
  // ⚠ THE OTHER ASSERTIONS IN THIS FILE DO NOT COVER IT. They check `Content-Type` and
  // `Cache-Control`, so deleting the Authorization line leaves this suite entirely green while
  // every upload in the product fails. That is the whole reason these two exist.

  it('sends the bearer token, because the PUT goes to Mantle and not to a presigned link', async () => {
    localStorage.setItem('access_token', 'a-test-token');
    const file = new File(['x'], 'probe.txt', { type: 'text/plain' });
    mockXHR.status = 200;

    const promise = uploadWithProgress('workspace-1', 'upload-1', 'https://example.com/u', file);
    if (mockXHR.onload) mockXHR.onload();
    await promise;

    expect(mockXHR.setRequestHeader).toHaveBeenCalledWith('Authorization', 'Bearer a-test-token');
  });

  it('sends no Authorization header when there is no token, rather than an empty bearer', async () => {
    // `if (token)` is deliberate: `Bearer null` is a malformed credential, and a service that
    // rejects it reports an auth failure rather than the absence of one.
    localStorage.removeItem('access_token');
    const file = new File(['x'], 'probe.txt', { type: 'text/plain' });
    mockXHR.status = 200;

    const promise = uploadWithProgress('workspace-1', 'upload-1', 'https://example.com/u', file);
    if (mockXHR.onload) mockXHR.onload();
    await promise;

    const sent = mockXHR.setRequestHeader.mock.calls.map((c: unknown[]) => c[0]);
    expect(sent).not.toContain('Authorization');
  });
});

