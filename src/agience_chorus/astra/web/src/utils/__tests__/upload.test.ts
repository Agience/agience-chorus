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
});

