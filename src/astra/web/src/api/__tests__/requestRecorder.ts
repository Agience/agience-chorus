// src/api/__tests__/requestRecorder.ts
//
// Records what the shared axios instance actually puts on the wire, by swapping
// its adapter. Routing lives in an interceptor, so asserting a call's target
// means letting the real instance run and reading the request it produces —
// mocking the module under test would assert nothing about routing.
//
// The axios types here are the `@types/axios` stub, which predates
// `AxiosResponse` / adapters, hence the local shapes.

import api from '../api';

export type RecordedRequest = {
  url?: string;
  baseURL?: string;
  method?: string;
  params?: Record<string, unknown>;
  data?: string;
};

type Adapter = (config: RecordedRequest) => Promise<unknown>;
type Defaults = { adapter?: Adapter };

/** Install the recorder. Returns the (initially empty) log and a restore fn. */
export function recordRequests(replyWith: () => unknown): {
  requests: RecordedRequest[];
  restore: () => void;
} {
  const defaults = api.defaults as unknown as Defaults;
  const original = defaults.adapter;
  const requests: RecordedRequest[] = [];

  defaults.adapter = async (config: RecordedRequest) => {
    requests.push(config);
    return { data: replyWith(), status: 200, statusText: 'OK', headers: {}, config };
  };

  return { requests, restore: () => { defaults.adapter = original; } };
}
